import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OverdraftLine(models.Model):
    _name = 'overdraft.line'
    _description = 'Overdraft Line'
    _order = 'date asc, id asc'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    overdraft_id = fields.Many2one(
        'overdraft.interest',
        string='Overdraft',
        required=True,
        ondelete='cascade',
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
    )
    amount = fields.Float(
        string='Amount',
        required=True,
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='overdraft_id.currency_id',
        store=True,
        readonly=True,
    )
    interest = fields.Monetary(
        string='Interest',
        compute='_compute_interest',
        store=True,
        currency_field='currency_id',
    )
    penalty = fields.Monetary(
        string='Penalty',
        default=0.0,
        currency_field='currency_id',
    )
    payment = fields.Monetary(
        string='Payment',
        default=0.0,
        currency_field='currency_id',
    )
    total_balance = fields.Monetary(
        string='Total',
        compute='_compute_running_balances',
        store=False,
        currency_field='currency_id',
        help='Cumulative total of all overdraft amounts up to this line',
    )
    remaining_balance = fields.Monetary(
        string='Remaining',
        compute='_compute_running_balances',
        store=False,
        currency_field='currency_id',
        help='Remaining available balance from the overdraft limit',
    )
    notes = fields.Text(string='Notes')

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('amount', 'overdraft_id.daily_interest_rate')
    def _compute_interest(self):
        """Auto-calculate interest: |amount| * (rate / 100) / 365"""
        for line in self:
            if line.amount and line.overdraft_id and line.overdraft_id.daily_interest_rate:
                try:
                    abs_amount = abs(float(line.amount))
                    rate = float(line.overdraft_id.daily_interest_rate)
                    line.interest = round((abs_amount * rate / 100.0) / 365.0, 6)
                except (TypeError, ValueError) as e:
                    _logger.error("Interest calculation error: %s", e)
                    line.interest = 0.0
            else:
                line.interest = 0.0

    @api.depends(
        'amount', 'payment',
        'overdraft_id.overdraft_limit',
        'overdraft_id.overdraft_line_ids.amount',
        'overdraft_id.overdraft_line_ids.payment',
        'date',
    )
    def _compute_running_balances(self):
        """Calculate running total and remaining balance for each line."""
        for line in self:
            if not line.overdraft_id:
                line.total_balance = 0.0
                line.remaining_balance = 0.0
                continue

            # Sort all sibling lines by date, then by ID
            all_lines = line.overdraft_id.overdraft_line_ids
            sorted_lines = []
            for idx, l in enumerate(all_lines):
                date_val = l.date or fields.Date.today()
                id_val = l.id if isinstance(l.id, int) else idx
                sorted_lines.append((date_val, id_val, l))
            sorted_lines.sort(key=lambda x: (x[0], x[1]))

            # Accumulate up to and including this line
            cumulative_amount = 0.0
            cumulative_payments = 0.0
            for _, _, sorted_line in sorted_lines:
                cumulative_amount += abs(sorted_line.amount)
                cumulative_payments += sorted_line.payment
                if sorted_line == line:
                    break

            line.total_balance = cumulative_amount
            line.remaining_balance = (
                line.overdraft_id.overdraft_limit
                - (cumulative_amount - cumulative_payments)
            )

    # -------------------------------------------------------------------------
    # ONCHANGE
    # -------------------------------------------------------------------------
    @api.onchange('amount')
    def _onchange_amount(self):
        """Convert positive amounts to negative (overdraft = debit)."""
        if self.amount and self.amount > 0:
            self.amount = -self.amount

    @api.onchange('amount', 'overdraft_id.daily_penalty_rate')
    def _onchange_penalty(self):
        """Suggest penalty value (user can override)."""
        if self.amount and self.overdraft_id and self.overdraft_id.daily_penalty_rate:
            try:
                abs_amount = abs(float(self.amount))
                rate = float(self.overdraft_id.daily_penalty_rate)
                self.penalty = round((abs_amount * rate / 100.0) / 365.0, 6)
            except (TypeError, ValueError):
                self.penalty = 0.0

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    def write(self, vals):
        """Prevent non-managers from editing existing lines."""
        if not self.env.user.has_group(
            'overdraft_interest_calculator.group_overdraft_manager'
        ):
            raise UserError(_(
                'Only managers can edit existing overdraft entries. '
                'You can add new entries or contact your manager.'
            ))
        return super().write(vals)
