// Specification shadow for cp_uart, written from docs/SPEC.md.
//
// A direct restatement of the spec that predicts every output: the registers, the two
// FIFOs as shift queues, the frame position as (slot, cycle). It uses only the device's
// port names, so the same text is included by the black-box wrapper (cp_uart_props.sv,
// used on mutants) and, for the unbounded proof of the original design, inside the
// device module itself next to the refinement invariants (invariants.svh).
// Every name defined here starts with s_ or SA_.

  // ------------------------------------------------------------------ APB decode (SPEC 3)
  localparam SA_CTRL = 8'h00, SA_BAUD = 8'h04, SA_STATUS = 8'h08, SA_TXDATA = 8'h0C,
             SA_RXDATA = 8'h10, SA_IRQ_EN = 8'h14, SA_IRQ_STAT = 8'h18;

  wire s_mapped = paddr == SA_CTRL || paddr == SA_BAUD || paddr == SA_STATUS || paddr == SA_TXDATA ||
                  paddr == SA_RXDATA || paddr == SA_IRQ_EN || paddr == SA_IRQ_STAT;
  wire s_bad    = !s_mapped || (pwrite && (paddr == SA_STATUS || paddr == SA_RXDATA));
  wire s_done   = psel && penable;               // the transfer completes at the coming edge
  wire s_wr     = s_done &&  pwrite && !s_bad;
  wire s_rd     = s_done && !pwrite && !s_bad;

  // ------------------------------------------------------------------ shadow state
  reg [5:0]  s_ctrl;
  reg [7:0]  s_baud;
  reg [5:0]  s_irq_en, s_irq_stat;

  reg [31:0] s_txq;                              // TX queue, head in [7:0]
  reg [2:0]  s_txn;
  reg        s_tx_busy, s_txd;
  reg [3:0]  s_tx_slot;                          // 0 start, 1..8 data, 9.. parity / stop
  reg [7:0]  s_tx_cyc, s_tx_div, s_tx_byte;
  reg        s_tx_par_en, s_tx_par_odd, s_tx_stop2;

  reg [39:0] s_rxq;                              // RX queue of {ferr, perr, data}, head in [9:0]
  reg [2:0]  s_rxn;
  reg        s_s1, s_s2;
  reg        s_rx_busy;
  reg [3:0]  s_rx_idx;                           // 0 start check, 1..8 data, 9 parity or stop, 10 stop
  reg [7:0]  s_rx_wait, s_rx_div, s_rx_data;
  reg        s_rx_par_en, s_rx_par_odd, s_rx_perr_q;

  // ------------------------------------------------------------------ transmitter (SPEC 5)
  wire [3:0] s_tx_last  = 4'd9 + {3'd0, s_tx_par_en} + {3'd0, s_tx_stop2};
  wire       s_tx_avail = !s_tx_busy || (s_tx_slot == s_tx_last && s_tx_cyc == s_tx_div);
  wire       s_tx_start = s_tx_avail && s_ctrl[0] && s_txn != 3'd0;
  wire       s_tx_push  = s_wr && paddr == SA_TXDATA && s_txn != 3'd4;
  wire       s_tx_ovf   = s_wr && paddr == SA_TXDATA && s_txn == 3'd4;

  function automatic s_slot_bit(input [3:0] slot, input [7:0] b, input par_en, input par_odd);
    begin
      if (slot == 4'd0)                 s_slot_bit = 1'b0;
      else if (slot <= 4'd8)            s_slot_bit = b[slot - 4'd1];
      else if (slot == 4'd9 && par_en)  s_slot_bit = (^b) ^ par_odd;
      else                              s_slot_bit = 1'b1;
    end
  endfunction

  // ------------------------------------------------------------------ receiver (SPEC 6)
  wire       s_rx_in      = s_ctrl[4] ? s_txd : rxd;
  wire       s_rx_detect  = !s_rx_busy && s_ctrl[1] && !s_s2;
  wire       s_rx_sample  = s_rx_busy && s_rx_wait == 8'd0;
  wire       s_rx_is_stop = s_rx_sample && (s_rx_idx == 4'd10 || (s_rx_idx == 4'd9 && !s_rx_par_en));
  wire       s_rx_perr    = s_rx_par_en && s_rx_perr_q;
  wire       s_rx_ferr    = !s_s2;
  wire       s_rx_push    = s_rx_is_stop && s_rxn != 3'd4;
  wire       s_rx_ovr     = s_rx_is_stop && s_rxn == 3'd4;
  wire       s_rx_pop     = s_rd && paddr == SA_RXDATA && s_rxn != 3'd0;
  wire [9:0] s_rx_entry   = {s_rx_ferr, s_rx_perr, s_rx_data};

  // ------------------------------------------------------------------ events (SPEC 4.6)
  wire [5:0] s_irq_set = { s_tx_ovf,
                           s_rx_is_stop && s_rx_ferr,
                           s_rx_is_stop && s_rx_perr,
                           s_rx_ovr,
                           s_rx_push,
                           s_tx_start && s_txn == 3'd1 && !s_tx_push };
  wire [5:0] s_irq_clr = (s_wr && paddr == SA_IRQ_STAT) ? pwdata[5:0] : 6'd0;

  wire [2:0] s_txn_after_pop = s_txn - {2'd0, s_tx_start};
  wire [2:0] s_rxn_after_pop = s_rxn - {2'd0, s_rx_pop};

  // The queues after this edge's pop, before this edge's push.
  wire [31:0] s_txq_popped = s_tx_start ? {8'd0, s_txq[31:8]}   : s_txq;
  wire [39:0] s_rxq_popped = s_rx_pop   ? {10'd0, s_rxq[39:10]} : s_rxq;

  always @(posedge pclk) begin
    if (!presetn) begin
      s_ctrl <= 0; s_baud <= 0; s_irq_en <= 0; s_irq_stat <= 0;
      s_txq <= 0; s_txn <= 0; s_tx_busy <= 0; s_txd <= 1; s_tx_slot <= 0; s_tx_cyc <= 0;
      s_tx_div <= 0; s_tx_byte <= 0; s_tx_par_en <= 0; s_tx_par_odd <= 0; s_tx_stop2 <= 0;
      s_rxq <= 0; s_rxn <= 0; s_s1 <= 1; s_s2 <= 1; s_rx_busy <= 0; s_rx_idx <= 0;
      s_rx_wait <= 0; s_rx_div <= 0; s_rx_data <= 0; s_rx_par_en <= 0; s_rx_par_odd <= 0; s_rx_perr_q <= 0;
    end else begin
      if (s_wr && paddr == SA_CTRL)   s_ctrl   <= pwdata[5:0];
      if (s_wr && paddr == SA_BAUD)   s_baud   <= pwdata[7:0];
      if (s_wr && paddr == SA_IRQ_EN) s_irq_en <= pwdata[5:0];
      s_irq_stat <= (s_irq_stat & ~s_irq_clr) | s_irq_set;    // set wins

      // TX queue: pop the head, then append behind what is left
      s_txq <= s_txq_popped;
      if (s_tx_push) begin
        case (s_txn_after_pop)
          3'd0:    s_txq <= {s_txq_popped[31:8],  pwdata[7:0]};
          3'd1:    s_txq <= {s_txq_popped[31:16], pwdata[7:0], s_txq_popped[7:0]};
          3'd2:    s_txq <= {s_txq_popped[31:24], pwdata[7:0], s_txq_popped[15:0]};
          default: s_txq <= {pwdata[7:0], s_txq_popped[23:0]};
        endcase
      end
      s_txn <= s_txn_after_pop + {2'd0, s_tx_push};

      // TX frame position
      if (s_tx_start) begin
        s_tx_busy <= 1; s_tx_slot <= 0; s_tx_cyc <= 0; s_txd <= 0;
        s_tx_byte <= s_txq[7:0]; s_tx_div <= s_baud;
        s_tx_par_en <= s_ctrl[2]; s_tx_par_odd <= s_ctrl[3]; s_tx_stop2 <= s_ctrl[5];
      end else if (s_tx_busy) begin
        if (s_tx_cyc != s_tx_div) begin
          s_tx_cyc <= s_tx_cyc + 8'd1;
        end else if (s_tx_slot == s_tx_last) begin
          s_tx_busy <= 0; s_txd <= 1;
        end else begin
          s_tx_cyc <= 0; s_tx_slot <= s_tx_slot + 4'd1;
          s_txd <= s_slot_bit(s_tx_slot + 4'd1, s_tx_byte, s_tx_par_en, s_tx_par_odd);
        end
      end

      // RX input path
      s_s1 <= s_rx_in;  s_s2 <= s_s1;

      // RX frame position
      if (s_rx_detect) begin
        s_rx_busy <= 1; s_rx_div <= s_baud; s_rx_par_en <= s_ctrl[2]; s_rx_par_odd <= s_ctrl[3];
        s_rx_perr_q <= 0;
        if (s_baud[7:1] == 7'd0) begin s_rx_idx <= 1; s_rx_wait <= s_baud; end          // h = 0
        else                     begin s_rx_idx <= 0; s_rx_wait <= {1'b0, s_baud[7:1]} - 8'd1; end
      end else if (s_rx_busy) begin
        if (!s_rx_sample) begin
          s_rx_wait <= s_rx_wait - 8'd1;
        end else if (s_rx_idx == 4'd0 && s_s2) begin
          s_rx_busy <= 0;                                                              // false start
        end else if (s_rx_is_stop) begin
          s_rx_busy <= 0;
        end else begin
          s_rx_wait <= s_rx_div;  s_rx_idx <= s_rx_idx + 4'd1;
          if (s_rx_idx >= 4'd1 && s_rx_idx <= 4'd8) s_rx_data[s_rx_idx - 4'd1] <= s_s2;
          if (s_rx_idx == 4'd9) s_rx_perr_q <= ((^s_rx_data) ^ s_s2) != s_rx_par_odd;
        end
      end

      // RX queue, same shape
      s_rxq <= s_rxq_popped;
      if (s_rx_push) begin
        case (s_rxn_after_pop)
          3'd0:    s_rxq <= {s_rxq_popped[39:10], s_rx_entry};
          3'd1:    s_rxq <= {s_rxq_popped[39:20], s_rx_entry, s_rxq_popped[9:0]};
          3'd2:    s_rxq <= {s_rxq_popped[39:30], s_rx_entry, s_rxq_popped[19:0]};
          default: s_rxq <= {s_rx_entry, s_rxq_popped[29:0]};
        endcase
      end
      s_rxn <= s_rxn_after_pop + {2'd0, s_rx_push};
    end
  end

  // ------------------------------------------------------------------ expected outputs
  wire [31:0] s_e_status = {17'd0, s_rxn, 1'b0, s_txn, 2'd0, s_rx_busy, s_tx_busy,
                            s_rxn == 3'd4, s_rxn == 3'd0, s_txn == 3'd4, s_txn == 3'd0};
  wire [31:0] s_e_rxdata = (s_rxn == 3'd0) ? 32'd0 : {22'd0, s_rxq[9:0]};

  reg [31:0] s_e_prdata;
  always @(*) begin
    s_e_prdata = 32'd0;
    if (psel && !pwrite) begin
      case (paddr)
        SA_CTRL:     s_e_prdata = {26'd0, s_ctrl};
        SA_BAUD:     s_e_prdata = {24'd0, s_baud};
        SA_STATUS:   s_e_prdata = s_e_status;
        SA_RXDATA:   s_e_prdata = s_e_rxdata;
        SA_IRQ_EN:   s_e_prdata = {26'd0, s_irq_en};
        SA_IRQ_STAT: s_e_prdata = {26'd0, s_irq_stat};
        default:     s_e_prdata = 32'd0;
      endcase
    end
  end
