// cp_fifo -- the 4-deep synchronous FIFO used for both UART directions.
//
// The FIFO is deliberately "dumb": it never decides whether a push or a pop is
// legal.  The top level evaluates full/empty against the pre-edge count and
// only asserts push/pop when the operation is actually accepted.  Keeping the
// decision at the top is what makes the same-edge ordering rules of SPEC
// section 7 fall out for free -- in particular a push and a pop at the same
// edge must leave the count unchanged, while a push into a full FIFO must be
// dropped even though a pop happens at that same edge.
//
// Depth is fixed at 4 (SPEC section 1); only the entry width is parameterised
// so the RX side can carry its two error flags alongside the data byte.
module cp_fifo #(
    parameter int WIDTH = 8
) (
    input  logic             pclk,
    input  logic             presetn,   // synchronous, active low
    input  logic             push,      // accepted push; caller guarantees count < 4
    input  logic [WIDTH-1:0] wdata,
    input  logic             pop,       // accepted pop;  caller guarantees count > 0
    output logic [WIDTH-1:0] rdata,     // head entry, meaningful when count > 0
    output logic [2:0]       count      // 0 .. 4
`ifdef CP_FORMAL_WHITEBOX
    // Formal only: the storage and pointers, so the proof can state how the contents
    // correspond to the specification. Never present in simulation or synthesis.
    , output logic [4*WIDTH-1:0] fv_mem
    , output logic [1:0]         fv_rptr
    , output logic [1:0]         fv_wptr
`endif
);

  logic [WIDTH-1:0] mem [0:3];
  logic [1:0]       rptr;
  logic [1:0]       wptr;

  // Asynchronous head read: both the transmitter and the APB read path need the
  // pre-edge head value at the very edge that pops it.
  assign rdata = mem[rptr];

`ifdef CP_FORMAL_WHITEBOX
  assign fv_mem  = {mem[3], mem[2], mem[1], mem[0]};
  assign fv_rptr = rptr;
  assign fv_wptr = wptr;
`endif

  always_ff @(posedge pclk) begin
    if (!presetn) begin
      // SPEC section 8: both FIFOs reset empty with all storage 0.
      for (int i = 0; i < 4; i++) begin
        mem[i] <= '0;
      end
      rptr  <= 2'd0;
      wptr  <= 2'd0;
      count <= 3'd0;
    end else begin
      if (push) begin
        mem[wptr] <= wdata;
        wptr      <= wptr + 2'd1;
      end
      if (pop) begin
        rptr <= rptr + 2'd1;
      end
      case ({push, pop})
        2'b10:   count <= count + 3'd1;
        2'b01:   count <= count - 3'd1;
        default: count <= count;  // idle, or a simultaneous push and pop
      endcase
    end
  end

endmodule
