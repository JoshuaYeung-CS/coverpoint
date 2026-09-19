// One assertion per output: the device agrees with the specification shadow.
// Outputs mean nothing before the first reset edge (f_init is that first cycle).

  always @(*) begin
    if (!f_init) begin
      a_pready:      assert (pready);
      a_pslverr:     assert (pslverr == (s_done && s_bad));
      a_txd:         assert (txd == s_txd);
      a_irq:         assert (irq == ((s_irq_stat & s_irq_en) != 6'd0));
      a_rd_idle:     assert (!(!psel || pwrite) || prdata == 32'd0);
      if (psel && !pwrite) begin
        a_rd_ctrl:     assert (paddr != SA_CTRL     || prdata == s_e_prdata);
        a_rd_baud:     assert (paddr != SA_BAUD     || prdata == s_e_prdata);
        a_rd_status:   assert (paddr != SA_STATUS   || prdata == s_e_prdata);
        a_rd_txdata:   assert (paddr != SA_TXDATA   || prdata == s_e_prdata);
        a_rd_rxdata:   assert (paddr != SA_RXDATA   || prdata == s_e_prdata);
        a_rd_irq_en:   assert (paddr != SA_IRQ_EN   || prdata == s_e_prdata);
        a_rd_irq_stat: assert (paddr != SA_IRQ_STAT || prdata == s_e_prdata);
        a_rd_unmapped: assert (s_mapped              || prdata == 32'd0);
      end
    end
  end
