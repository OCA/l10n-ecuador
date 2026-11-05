This module pre-fills the boxes of the SRI monthly IVA return (Formulario
104) that derive from the posted moves of the reported month, with
traceability from every prefilled box back to its documents.

It does not reimplement what Odoo core already computes: the 104 report of
`l10n_ec` (engine `tax_tags`, ~110 lines) already derives the sales/purchase
summaries, the 5% materials boxes, the 423/424 and 526/527 adjustments and the
perception/withholding frame. Those boxes are read, never recalculated. What
this module adds is the layer core does not ship: the variable-rate boxes
(410/420/430, 530/533/534), the credit-sale settlement (480-485/499), the
slip counts (111/113/115/117/119), the proportionality factor (563) with its
suggested credit (564/565), and the wizard that composes them.
