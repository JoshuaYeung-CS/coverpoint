// Refinement invariants: how the device's internal state corresponds to the
// specification shadow. Used only for the unbounded proof of the original design, where
// this file is included inside the device module and can see its registers.
//
// Why they are needed: induction starts from an ARBITRARY state that satisfies the
// assertions, not from reset. "The outputs agree" alone is far too weak for that: the
// solver simply picks a device state and a shadow state that happen to agree now and
// disagree one cycle later, and reports the step as failed (UNKNOWN, not a bug). Stating
// that the two states correspond, field by field, rules those starting points out, and
// then one step of induction is enough because both sides are deterministic functions of
// corresponding state and the same inputs.

  // Entry i of each device FIFO, counted from its read pointer.
  wire [1:0] fv_txi1 = fv_tx_rptr + 2'd1, fv_txi2 = fv_tx_rptr + 2'd2, fv_txi3 = fv_tx_rptr + 2'd3;
  wire [1:0] fv_rxi1 = fv_rx_rptr + 2'd1, fv_rxi2 = fv_rx_rptr + 2'd2, fv_rxi3 = fv_rx_rptr + 2'd3;

  always @(*) begin
    if (!f_init) begin
      // programmer-visible registers
      i_ctrl:     assert (ctrl == s_ctrl);
      i_baud:     assert (baud_div == s_baud);
      i_irq_en:   assert (irq_en == s_irq_en);
      i_irq_stat: assert (irq_stat == s_irq_stat);

      // transmitter: same frame, same position in it
      i_tx_busy:  assert (tx_active == s_tx_busy);
      if (tx_active) begin
        i_tx_slot:  assert (tx_slot == s_tx_slot);
        i_tx_phase: assert (tx_phase == s_tx_cyc);
        i_tx_div:   assert (tx_div == s_tx_div);
        i_tx_last:  assert (tx_last_slot == s_tx_last);
        i_tx_frame: assert (tx_frame == {2'b11, s_tx_par_en ? ((^s_tx_byte) ^ s_tx_par_odd) : 1'b1,
                                         s_tx_byte, 1'b0});
      end

      // receiver: same synchroniser contents, same frame, same position, same bits so far
      i_sync:     assert (s1 == s_s1 && s2 == s_s2);
      i_rx_busy:  assert (rx_active == s_rx_busy);
      if (rx_active) begin
        i_rx_slot:  assert (rx_slot == s_rx_idx);
        i_rx_timer: assert (rx_timer == s_rx_wait);
        i_rx_cfg:   assert (rx_div == s_rx_div && rx_par_en == s_rx_par_en && rx_par_odd == s_rx_par_odd);
        i_rx_perr:  assert (rx_perr == s_rx_perr_q);
        i_rx_range: assert (rx_slot <= 4'd10);
        // A reachability fact, not a correspondence: the parity-error flag can only be
        // set on a frame that carries parity. The device relies on it (it does not gate
        // the flag again when it builds the FIFO entry); induction has to be told.
        i_rx_perr_needs_parity: assert (rx_par_en || !rx_perr);
        // The device shifts bits in from the top; the shadow writes them in place.
        case (rx_slot)
          4'd2:    i_rx_d1: assert (rx_data[7]   == s_rx_data[0]);
          4'd3:    i_rx_d2: assert (rx_data[7:6] == s_rx_data[1:0]);
          4'd4:    i_rx_d3: assert (rx_data[7:5] == s_rx_data[2:0]);
          4'd5:    i_rx_d4: assert (rx_data[7:4] == s_rx_data[3:0]);
          4'd6:    i_rx_d5: assert (rx_data[7:3] == s_rx_data[4:0]);
          4'd7:    i_rx_d6: assert (rx_data[7:2] == s_rx_data[5:0]);
          4'd8:    i_rx_d7: assert (rx_data[7:1] == s_rx_data[6:0]);
          4'd9:    i_rx_d8: assert (rx_data      == s_rx_data);
          4'd10:   i_rx_d9: assert (rx_data      == s_rx_data);
          default: ;
        endcase
      end

      // FIFOs: same occupancy, pointers consistent with it, same live entries in order
      i_tx_count: assert (tx_count == s_txn && tx_count <= 3'd4);
      i_tx_ptrs:  assert (fv_tx_wptr == fv_tx_rptr + tx_count[1:0]);
      if (s_txn > 3'd0) i_tx_e0: assert (fv_tx_mem[8 * fv_tx_rptr +: 8] == s_txq[7:0]);
      if (s_txn > 3'd1) i_tx_e1: assert (fv_tx_mem[8 * fv_txi1    +: 8] == s_txq[15:8]);
      if (s_txn > 3'd2) i_tx_e2: assert (fv_tx_mem[8 * fv_txi2    +: 8] == s_txq[23:16]);
      if (s_txn > 3'd3) i_tx_e3: assert (fv_tx_mem[8 * fv_txi3    +: 8] == s_txq[31:24]);

      i_rx_count: assert (rx_count == s_rxn && rx_count <= 3'd4);
      i_rx_ptrs:  assert (fv_rx_wptr == fv_rx_rptr + rx_count[1:0]);
      if (s_rxn > 3'd0) i_rx_e0: assert (fv_rx_mem[10 * fv_rx_rptr +: 10] == s_rxq[9:0]);
      if (s_rxn > 3'd1) i_rx_e1: assert (fv_rx_mem[10 * fv_rxi1    +: 10] == s_rxq[19:10]);
      if (s_rxn > 3'd2) i_rx_e2: assert (fv_rx_mem[10 * fv_rxi2    +: 10] == s_rxq[29:20]);
      if (s_rxn > 3'd3) i_rx_e3: assert (fv_rx_mem[10 * fv_rxi3    +: 10] == s_rxq[39:30]);
    end
  end
