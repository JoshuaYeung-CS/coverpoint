// Environment assumptions shared by every formal run in this project.
//
// They are the same promises the simulation bench keeps: reset comes first, and the APB
// master obeys the protocol (penable exactly in the cycle after a setup cycle, with the
// address, direction and data held). Nothing here looks inside the device.
//
// `FV_MAX_DIV bounds the baud divisor the solver may program. A serial frame takes
// 10 * (div + 1) cycles, so without a bound no interesting behaviour fits inside a
// bounded proof. The property runs state this bound next to every result.

reg        f_init  = 1'b1;
reg        f_setup = 1'b0;
reg        f_pwrite;
reg [7:0]  f_paddr;
reg [31:0] f_pwdata;

always @(posedge pclk) begin
  f_init   <= 1'b0;
  f_setup  <= psel && !penable;
  f_pwrite <= pwrite;
  f_paddr  <= paddr;
  f_pwdata <= pwdata;
end

always @(*) begin
  if (f_init) assume (!presetn);
  assume (penable == f_setup);
  if (penable) assume (psel);
  if (penable) assume (pwrite == f_pwrite && paddr == f_paddr && pwdata == f_pwdata);
`ifdef FV_MAX_DIV
  if (psel && pwrite && paddr == 8'h04) assume (pwdata[7:0] <= `FV_MAX_DIV);
`endif
end
