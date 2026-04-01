from odoo import models, fields


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Reverse links — one for each loan type
    overdraft_id = fields.Many2one(
        'overdraft.interest',
        string='Overdraft Interest',
        ondelete='set null',
        index=True,
    )
    term_loan_id = fields.Many2one(
        'term.loan',
        string='Term Loan',
        ondelete='set null',
        index=True,
    )
    merchandise_loan_id = fields.Many2one(
        'merchandise.loan',
        string='Merchandise Loan',
        ondelete='set null',
        index=True,
    )
    preshipment_loan_id = fields.Many2one(
        'preshipment.loan',
        string='Pre-Shipment Loan',
        ondelete='set null',
        index=True,
    )
