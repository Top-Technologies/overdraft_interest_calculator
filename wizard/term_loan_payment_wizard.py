from odoo import models, fields, api, _
from odoo.exceptions import UserError


class TermLoanPaymentWizard(models.TransientModel):
    _name = 'term.loan.payment.wizard'
    _description = 'Record Term Loan Extra Payment'

    loan_id = fields.Many2one(
        'term.loan',
        string='Term Loan',
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='loan_id.currency_id',
        readonly=True,
    )
    line_id = fields.Many2one(
        'term.loan.line',
        string='Payment Line',
        required=True,
        domain="[('loan_id', '=', loan_id), ('ending_balance', '>', 0)]",
        help='Select the schedule line to apply the extra payment to.',
    )
    penalty_accrued = fields.Monetary(
        string='Penalty Accrued',
        related='line_id.penalty_amount',
        readonly=True,
    )
    date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.context_today,
    )
    amount = fields.Monetary(
        string='Extra Payment Amount',
        required=True,
        currency_field='currency_id',
    )
    memo = fields.Char(string='Memo')

    @api.onchange('loan_id')
    def _onchange_loan_id(self):
        """Auto-select the first unpaid line."""
        if self.loan_id:
            lines = self.loan_id.loan_line_ids.sorted('payment_number')
            unpaid = lines.filtered(lambda l: l.ending_balance > 0)
            if unpaid:
                self.line_id = unpaid[0].id

    def action_confirm(self):
        """Record the payment on the selected schedule line, mark it as paid,
        and trigger recalculation."""
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Payment amount must be greater than zero.'))

        line = self.line_id
        if not line:
            raise UserError(_('Please select a payment line.'))

        # Mark line as paid, set the date, and update extra payment
        line.sudo().write({
            'is_paid': True,
            'paid_date': self.date,
            'extra_payment': line.extra_payment + self.amount,
        })

        # Trigger recalculation of the schedule
        self.loan_id.sudo().action_recalculate_schedule()

        # Post clean log note in chatter using Markup
        from markupsafe import Markup
        user_name = self.env.user.name
        symbol = self.currency_id.symbol or ''
        pmt_no = line.payment_number

        if self.amount > 0:
            formatted_total = f"{line.total_payment:,.2f} {symbol}"
            formatted_extra = f"{self.amount:,.2f} {symbol}"
            payment_desc = f"{formatted_total} (includes {formatted_extra} Extra Payment)"
        else:
            formatted_total = f"{line.total_payment:,.2f} {symbol}"
            payment_desc = f"{formatted_total}"

        message_body = Markup(
            "<b>Payment Recorded:</b> %s for Payment #%s on %s by %s"
        ) % (payment_desc, pmt_no, self.date, user_name)
        if self.memo:
            message_body += Markup(" (Memo: %s)") % self.memo
        self.loan_id.message_post(body=message_body, message_type='comment', subtype_xmlid='mail.mt_note')

        return {'type': 'ir.actions.act_window_close'}
