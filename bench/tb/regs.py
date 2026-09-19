"""Register map constants, straight from docs/SPEC.md section 4."""
CTRL, BAUD, STATUS, TXDATA, RXDATA, IRQ_EN, IRQ_STAT = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18
MAPPED = (CTRL, BAUD, STATUS, TXDATA, RXDATA, IRQ_EN, IRQ_STAT)
NAMES = {CTRL: "CTRL", BAUD: "BAUD", STATUS: "STATUS", TXDATA: "TXDATA", RXDATA: "RXDATA",
         IRQ_EN: "IRQ_EN", IRQ_STAT: "IRQ_STAT"}
READ_ONLY = (STATUS, RXDATA)

TX_EN, RX_EN, PAR_EN, PAR_ODD, LOOPBACK, STOP2 = (1 << i for i in range(6))

ST_TX_EMPTY, ST_TX_FULL, ST_RX_EMPTY, ST_RX_FULL, ST_TX_BUSY, ST_RX_BUSY = (1 << i for i in range(6))

IRQ_TX_EMPTY, IRQ_RX_AVAIL, IRQ_RX_OVR, IRQ_PERR, IRQ_FERR, IRQ_TX_OVF = (1 << i for i in range(6))
IRQ_NAMES = ("tx_empty_ev", "rx_avail_ev", "rx_ovr", "perr_ev", "ferr_ev", "tx_ovf")

FIFO_DEPTH = 4


def tx_count(status: int) -> int:
    return (status >> 8) & 7


def rx_count(status: int) -> int:
    return (status >> 12) & 7
