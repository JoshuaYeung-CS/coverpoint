// Formal property set for cp_uart.
//
// Everything here is written from docs/SPEC.md and looks only at the device's ports, so
// the same file checks the original design and every mutant of it.
//
// The shape is a specification shadow (shadow.svh): a small, direct restatement of the
// spec that predicts every output, plus one assertion per output saying the device
// agrees (asserts.svh). The property set is therefore complete: it fixes every output in
// every cycle, so a design satisfies it if and only if it behaves as specified.
//
// What the solver explores is every legal input sequence (formal/env.svh) up to the
// bound, which is where this differs from simulation: no stimulus is chosen by anyone.

`ifndef MUT
`define MUT 0
`endif

module cp_uart_fv (
  input         pclk,
  input         presetn,
  input         psel,
  input         penable,
  input         pwrite,
  input  [7:0]  paddr,
  input  [31:0] pwdata,
  input         rxd
);
  wire [31:0] prdata;
  wire        pready, pslverr, txd, irq;

  cp_uart dut (
    .pclk(pclk), .presetn(presetn), .psel(psel), .penable(penable), .pwrite(pwrite),
    .paddr(paddr), .pwdata(pwdata), .prdata(prdata), .pready(pready), .pslverr(pslverr),
    .rxd(rxd), .txd(txd), .irq(irq)
`ifndef FV_NO_MUTSEL
    , .mutsel(16'd`MUT)
`endif
  );

`include "env.svh"

`include "shadow.svh"
`include "asserts.svh"
endmodule
