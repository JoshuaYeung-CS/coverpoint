// cp_uart -- APB3 UART with a 4-deep TX FIFO, a 4-deep RX FIFO and one
// interrupt output.  Implements docs/SPEC.md exactly; section references below
// point at that document.
//
// Everything is one clock domain and every decision is taken from pre-edge
// values, which is what makes the same-edge ordering of section 7 automatic:
// the combinational blocks read register state only, and the single always_ff
// commits all of it at once.
module cp_uart (
    input  logic        pclk,
    input  logic        presetn,  // synchronous reset, active low
    input  logic        psel,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [7:0]  paddr,
    input  logic [31:0] pwdata,
    output logic [31:0] prdata,
    output logic        pready,
    output logic        pslverr,
    input  logic        rxd,
    output logic        txd,
    output logic        irq
);

  // ------------------------------------------------------------------
  // Register map (SPEC section 4).  All eight address bits are decoded,
  // so 0x01 and friends are unmapped and therefore errors.
  // ------------------------------------------------------------------
  localparam [7:0] ADDR_CTRL     = 8'h00;
  localparam [7:0] ADDR_BAUD     = 8'h04;
  localparam [7:0] ADDR_STATUS   = 8'h08;
  localparam [7:0] ADDR_TXDATA   = 8'h0C;
  localparam [7:0] ADDR_RXDATA   = 8'h10;
  localparam [7:0] ADDR_IRQ_EN   = 8'h14;
  localparam [7:0] ADDR_IRQ_STAT = 8'h18;

  // ------------------------------------------------------------------
  // Architectural state
  // ------------------------------------------------------------------
  logic [5:0] ctrl;       // {stop2, loopback, par_odd, par_en, rx_en, tx_en}
  logic [7:0] baud_div;   // BAUD[7:0] = div; one bit lasts P = div + 1 cycles
  logic [5:0] irq_en;
  logic [5:0] irq_stat;

  // Transmitter
  logic        tx_active;
  logic [11:0] tx_frame;      // slot 0 = start, 1..8 = data LSB first,
                              // 9 = parity or stop, 10..11 = stop
  logic [3:0]  tx_last_slot;  // N - 1 = 9 + par_en + stop2
  logic [7:0]  tx_div;        // captured div; bit period P = tx_div + 1
  logic [3:0]  tx_slot;
  logic [7:0]  tx_phase;      // 0 .. tx_div within the current slot

  // Receiver
  logic       s1, s2;         // two-flop synchroniser on the serial input
  logic       rx_active;
  logic [7:0] rx_div;
  logic       rx_par_en;
  logic       rx_par_odd;
  logic [3:0] rx_slot;        // 0 = awaiting start check, 1..8 = data,
                              // 9 = parity or stop, 10 = stop
  logic [7:0] rx_timer;       // edges remaining before the next sample edge
  logic [7:0] rx_data;
  logic       rx_perr;

  // FIFO interfaces
  logic [7:0] tx_head;
  logic [2:0] tx_count;
  logic       tx_push, tx_pop;
  logic [9:0] rx_head;        // {ferr, perr, data[7:0]}
  logic [2:0] rx_count;
  logic       rx_push, rx_pop;

  // CTRL field aliases (SPEC section 4.1)
  logic ctrl_tx_en, ctrl_rx_en, ctrl_par_en, ctrl_par_odd, ctrl_loopback, ctrl_stop2;
  assign ctrl_tx_en    = ctrl[0];
  assign ctrl_rx_en    = ctrl[1];
  assign ctrl_par_en   = ctrl[2];
  assign ctrl_par_odd  = ctrl[3];
  assign ctrl_loopback = ctrl[4];
  assign ctrl_stop2    = ctrl[5];

  // ------------------------------------------------------------------
  // APB decode (SPEC section 3).  A transfer completes at an edge whose
  // pre-edge psel and penable are both 1; the setup phase does nothing.
  // ------------------------------------------------------------------
  logic addr_mapped;
  always_comb begin
    case (paddr)
      ADDR_CTRL, ADDR_BAUD, ADDR_STATUS, ADDR_TXDATA,
      ADDR_RXDATA, ADDR_IRQ_EN, ADDR_IRQ_STAT: addr_mapped = 1'b1;
      default:                                 addr_mapped = 1'b0;
    endcase
  end

  logic acc_err, acc_done, wr_done, rd_done;
  // Errors: unmapped address, or a write to a read-only register.  A read of
  // the write-only TXDATA is explicitly not an error.
  assign acc_err  = !addr_mapped ||
                    (pwrite && ((paddr == ADDR_STATUS) || (paddr == ADDR_RXDATA)));
  assign acc_done = psel && penable && !acc_err;  // error accesses have no side effects
  assign wr_done  = acc_done &&  pwrite;
  assign rd_done  = acc_done && !pwrite;

  assign pready  = 1'b1;                              // no wait states
  assign pslverr = psel && penable && acc_err;

  // ------------------------------------------------------------------
  // FIFO push/pop decisions, all against pre-edge counts (SPEC 4.4/4.5/7)
  // ------------------------------------------------------------------
  logic tx_wr, tx_ovf_set;
  assign tx_wr      = wr_done && (paddr == ADDR_TXDATA);
  assign tx_push    = tx_wr && (tx_count != 3'd4);
  assign tx_ovf_set = tx_wr && (tx_count == 3'd4);  // dropped even if we pop this edge

  logic rx_rd;
  assign rx_rd  = rd_done && (paddr == ADDR_RXDATA);
  assign rx_pop = rx_rd && (rx_count != 3'd0);      // no pop when empty, even if we push

  // ------------------------------------------------------------------
  // Transmitter control (SPEC section 5)
  // ------------------------------------------------------------------
  // The transmitter is available while idle, and again at edge s + NP -- the
  // edge that ends the final stop bit, i.e. the edge at which the last slot's
  // last cycle is already behind us.
  logic tx_end_edge, tx_avail;
  assign tx_end_edge = tx_active && (tx_slot == tx_last_slot) && (tx_phase == tx_div);
  assign tx_avail    = !tx_active || tx_end_edge;
  assign tx_pop      = tx_avail && ctrl_tx_en && (tx_count != 3'd0);

  // Frame image, built once at the start edge from the pre-edge CTRL/BAUD
  // values.  Slot 9 carries the parity bit when par_en, otherwise the first
  // stop bit; slots 10 and 11 are always stop bits.
  logic tx_par_bit;
  assign tx_par_bit = (^tx_head) ^ ctrl_par_odd;  // even = XOR of data, odd = its inverse

  logic [11:0] tx_frame_load;
  logic [3:0]  tx_last_slot_load;
  assign tx_frame_load     = {2'b11, (ctrl_par_en ? tx_par_bit : 1'b1), tx_head, 1'b0};
  assign tx_last_slot_load = 4'd9 + {3'b000, ctrl_par_en} + {3'b000, ctrl_stop2};

  // txd is registered, so at every edge we drive the bit belonging to the slot
  // that the *next* cycle sits in.
  logic [3:0]  tx_slot_next;
  logic [15:0] tx_frame_pad;
  logic        tx_next_bit;
  assign tx_slot_next = (tx_phase == tx_div) ? (tx_slot + 4'd1) : tx_slot;
  assign tx_frame_pad = {4'b1111, tx_frame};  // padding keeps the select in range
  assign tx_next_bit  = tx_frame_pad[tx_slot_next];

  // ------------------------------------------------------------------
  // Receiver control (SPEC section 6)
  // ------------------------------------------------------------------
  // In loopback the receiver listens to the registered txd; the pin keeps
  // being driven normally and rxd is ignored.
  logic rx_in;
  assign rx_in = ctrl_loopback ? txd : rxd;

  logic rx_start_det, rx_sample, rx_false_start, rx_parity_edge, rx_stop_edge;
  assign rx_start_det   = !rx_active && ctrl_rx_en && !s2;
  assign rx_sample      = rx_active && (rx_timer == 8'd0);
  assign rx_false_start = rx_sample && (rx_slot == 4'd0) && s2;
  assign rx_parity_edge = rx_sample && (rx_slot == 4'd9) && rx_par_en;
  assign rx_stop_edge   = rx_sample && (((rx_slot == 4'd9) && !rx_par_en) ||
                                         (rx_slot == 4'd10));

  // "differs from par_odd" is a plain XOR of the three terms.
  logic rx_perr_now;
  assign rx_perr_now = (^rx_data) ^ s2 ^ rx_par_odd;

  logic rx_ferr_now, rx_ovr_set;
  assign rx_ferr_now = rx_stop_edge && !s2;
  assign rx_push     = rx_stop_edge && (rx_count != 3'd4);
  assign rx_ovr_set  = rx_stop_edge && (rx_count == 3'd4);  // overrun even if we pop this edge

  logic [9:0] rx_entry;
  assign rx_entry = {rx_ferr_now, rx_perr, rx_data};

  // h = div >> 1.  h == 0 means the detection edge is itself the start check.
  logic       rx_half_zero;
  logic [7:0] rx_half_minus1;
  assign rx_half_zero   = (baud_div[7:1] == 7'd0);
  assign rx_half_minus1 = {1'b0, baud_div[7:1]} - 8'd1;

  // ------------------------------------------------------------------
  // Interrupts (SPEC section 4.6)
  // ------------------------------------------------------------------
  logic [5:0] irq_set;
  assign irq_set[0] = (tx_count == 3'd1) && tx_pop && !tx_push;  // tx_empty_ev
  assign irq_set[1] = rx_push;                                   // rx_avail_ev
  assign irq_set[2] = rx_ovr_set;                                // rx_ovr
  assign irq_set[3] = rx_stop_edge && rx_perr;                   // perr_ev
  assign irq_set[4] = rx_ferr_now;                               // ferr_ev
  assign irq_set[5] = tx_ovf_set;                                // tx_ovf

  logic [5:0] irq_clr;
  assign irq_clr = (wr_done && (paddr == ADDR_IRQ_STAT)) ? pwdata[5:0] : 6'd0;

  assign irq = |(irq_stat & irq_en);  // depends on state only

  // ------------------------------------------------------------------
  // Read data (SPEC sections 3 and 4).  Combinational, no penable term:
  // prdata already shows the read value during the setup cycle.
  // ------------------------------------------------------------------
  logic [31:0] status_word;
  assign status_word = {17'd0,
                        rx_count,            // 14:12 rx_count
                        1'b0,                // 11
                        tx_count,            // 10:8  tx_count
                        2'b00,               // 7:6
                        rx_active,           // 5    rx_busy
                        tx_active,           // 4    tx_busy
                        (rx_count == 3'd4),  // 3    rx_full
                        (rx_count == 3'd0),  // 2    rx_empty
                        (tx_count == 3'd4),  // 1    tx_full
                        (tx_count == 3'd0)}; // 0    tx_empty

  logic [31:0] rxdata_word;
  assign rxdata_word = (rx_count != 3'd0) ? {22'd0, rx_head} : 32'd0;

  always_comb begin
    prdata = 32'd0;
    if (psel && !pwrite) begin
      case (paddr)
        ADDR_CTRL:     prdata = {26'd0, ctrl};
        ADDR_BAUD:     prdata = {24'd0, baud_div};
        ADDR_STATUS:   prdata = status_word;
        ADDR_TXDATA:   prdata = 32'd0;  // write-only, reads 0 (and is not an error)
        ADDR_RXDATA:   prdata = rxdata_word;
        ADDR_IRQ_EN:   prdata = {26'd0, irq_en};
        ADDR_IRQ_STAT: prdata = {26'd0, irq_stat};
        default:       prdata = 32'd0;  // unmapped read is an error and returns 0
      endcase
    end
  end

  // ------------------------------------------------------------------
  // State update
  // ------------------------------------------------------------------
  always_ff @(posedge pclk) begin
    if (!presetn) begin
      // SPEC section 8.
      ctrl         <= 6'd0;
      baud_div     <= 8'd0;
      irq_en       <= 6'd0;
      irq_stat     <= 6'd0;
      txd          <= 1'b1;
      tx_active    <= 1'b0;
      tx_frame     <= 12'd0;
      tx_last_slot <= 4'd0;
      tx_div       <= 8'd0;
      tx_slot      <= 4'd0;
      tx_phase     <= 8'd0;
      s1           <= 1'b1;
      s2           <= 1'b1;
      rx_active    <= 1'b0;
      rx_div       <= 8'd0;
      rx_par_en    <= 1'b0;
      rx_par_odd   <= 1'b0;
      rx_slot      <= 4'd0;
      rx_timer     <= 8'd0;
      rx_data      <= 8'd0;
      rx_perr      <= 1'b0;
    end else begin
      // -- register writes --------------------------------------------
      if (wr_done) begin
        case (paddr)
          ADDR_CTRL:   ctrl     <= pwdata[5:0];
          ADDR_BAUD:   baud_div <= pwdata[7:0];
          ADDR_IRQ_EN: irq_en   <= pwdata[5:0];
          default:     ;  // TXDATA pushes below; IRQ_STAT clears below
        endcase
      end

      // -- interrupt status: sticky, and set wins over write-1-to-clear
      irq_stat <= (irq_stat & ~irq_clr) | irq_set;

      // -- input synchroniser -----------------------------------------
      s1 <= rx_in;
      s2 <= s1;

      // -- transmitter -------------------------------------------------
      // Order is load bearing: a start at the frame-end edge is a back-to-back
      // frame with no idle cycle, so it must win over the "go idle" arm.
      if (tx_pop) begin
        tx_frame     <= tx_frame_load;
        tx_last_slot <= tx_last_slot_load;
        tx_div       <= baud_div;
        tx_slot      <= 4'd0;
        tx_phase     <= 8'd0;
        tx_active    <= 1'b1;
        txd          <= 1'b0;  // start bit, from this edge on
      end else if (tx_end_edge) begin
        tx_active <= 1'b0;
        txd       <= 1'b1;     // idle line
      end else if (tx_active) begin
        tx_slot  <= tx_slot_next;
        tx_phase <= (tx_phase == tx_div) ? 8'd0 : (tx_phase + 8'd1);
        txd      <= tx_next_bit;
      end

      // -- receiver ----------------------------------------------------
      // Order is load bearing too: start detection only runs while idle, so a
      // frame that completes at this edge cannot also start one here -- the
      // earliest new start is the following edge.
      if (rx_start_det) begin
        rx_active  <= 1'b1;
        rx_div     <= baud_div;
        rx_par_en  <= ctrl_par_en;
        rx_par_odd <= ctrl_par_odd;
        rx_data    <= 8'd0;
        rx_perr    <= 1'b0;
        if (rx_half_zero) begin
          // h == 0: this edge is the start check and it always passes, so the
          // next sample is data bit 0 at c + P.
          rx_slot  <= 4'd1;
          rx_timer <= baud_div;
        end else begin
          rx_slot  <= 4'd0;
          rx_timer <= rx_half_minus1;  // next sample edge is c + h
        end
      end else if (rx_sample) begin
        if (rx_false_start || rx_stop_edge) begin
          // Both outcomes leave the receiver idle from this edge on.
          rx_active <= 1'b0;
        end else begin
          rx_slot  <= rx_slot + 4'd1;
          rx_timer <= rx_div;          // next sample is one bit period later
          if ((rx_slot >= 4'd1) && (rx_slot <= 4'd8)) begin
            // Slots 1..8 carry data bits 0..7, LSB first, so shifting right
            // eight times leaves bit 0 in position 0.  Slot 9 (parity) must
            // not disturb the byte -- the parity check reads it.
            rx_data <= {s2, rx_data[7:1]};
          end
          if (rx_parity_edge) begin
            rx_perr <= rx_perr_now;
          end
        end
      end else if (rx_active) begin
        rx_timer <= rx_timer - 8'd1;
      end
    end
  end

`ifdef CP_FORMAL_WHITEBOX
  // Formal only (formal/): the specification shadow, the output assertions and the
  // refinement invariants sit inside the module for the unbounded proof, because the
  // invariants have to name internal registers. Nothing here exists in simulation,
  // synthesis or the mutated netlists.
  logic [31:0] fv_tx_mem;
  logic [39:0] fv_rx_mem;
  logic [1:0]  fv_tx_rptr, fv_tx_wptr, fv_rx_rptr, fv_rx_wptr;
`include "env.svh"
`include "shadow.svh"
`include "asserts.svh"
`ifndef CP_FORMAL_NO_INVARIANTS
`include "invariants.svh"
`endif
`endif

  // ------------------------------------------------------------------
  // FIFOs
  // ------------------------------------------------------------------
  cp_fifo #(.WIDTH(8)) u_tx_fifo (
      .pclk   (pclk),
      .presetn(presetn),
      .push   (tx_push),
      .wdata  (pwdata[7:0]),
      .pop    (tx_pop),
      .rdata  (tx_head),
      .count  (tx_count)
`ifdef CP_FORMAL_WHITEBOX
      , .fv_mem(fv_tx_mem), .fv_rptr(fv_tx_rptr), .fv_wptr(fv_tx_wptr)
`endif
  );

  cp_fifo #(.WIDTH(10)) u_rx_fifo (
      .pclk   (pclk),
      .presetn(presetn),
      .push   (rx_push),
      .wdata  (rx_entry),
      .pop    (rx_pop),
      .rdata  (rx_head),
      .count  (rx_count)
`ifdef CP_FORMAL_WHITEBOX
      , .fv_mem(fv_rx_mem), .fv_rptr(fv_rx_rptr), .fv_wptr(fv_rx_wptr)
`endif
  );

  // No register field is wider than eight bits (SPEC section 4), so the upper
  // write-data bits are intentionally unused; sink them to keep lint clean.
  logic _unused_pwdata;
  assign _unused_pwdata = &{1'b1, pwdata[31:8]};

endmodule
