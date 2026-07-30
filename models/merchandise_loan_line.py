from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date as dt_date


class MerchandiseLoanLine(models.Model):
    _name = 'merchandise.loan.line'
    _description = 'Merchandise Loan — Goods Release Entry'
    _order = 'date asc, id asc'

    loan_id = fields.Many2one(
        'merchandise.loan',
        string='Loan',
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        related='loan_id.currency_id',
        store=True,
        readonly=True,
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
    )

    # ── The user enters the quantity of goods to release ──
    goods_released_quantity = fields.Float(
        string='Goods to Release (Qty)',
        digits=(16, 3),
        help='Number of goods you want to take from the warehouse.',
    )

    goods_value = fields.Monetary(
        string='Goods Value',
        currency_field='currency_id',
        compute='_compute_goods_value',
        store=True,
        help='Principal value of the goods released (qty × unit price).',
    )
    
    # ── Auto-calculated fields ──
    interest = fields.Monetary(
        string='Interest',
        currency_field='currency_id',
        help='Daily interest accrued from last payment/activation until this date.',
    )
    penalty = fields.Monetary(
        string='Penalty',
        currency_field='currency_id',
        help='Penalty charged if goods are released after the loan end date.',
    )
    payment_amount = fields.Monetary(
        string='Total Payment',
        currency_field='currency_id',
        help='Principal (goods value) + Interest + Penalty',
    )
    outstanding_after = fields.Monetary(
        string='Outstanding After',
        currency_field='currency_id',
        compute='_compute_outstanding_after',
        store=True,
        readonly=True,
    )
    notes = fields.Text(string='Notes')

    @api.depends('goods_released_quantity', 'loan_id.goods_unit_price')
    def _compute_goods_value(self):
        for line in self:
            if line.loan_id:
                line.goods_value = (line.goods_released_quantity or 0.0) * (line.loan_id.goods_unit_price or 0.0)
            else:
                line.goods_value = 0.0

    # -------------------------------------------------------------------------
    # ONCHANGE — live interest & payment preview while typing (before save)
    # -------------------------------------------------------------------------
    @api.onchange('goods_released_quantity', 'date')
    def _onchange_compute_interest(self):
        """Calculate interest and total payment as soon as the quantity to
        release (or the entry date) is entered, without waiting for a save.
        Mirrors the logic in merchandise.loan._recalculate_line_interest():
        interest = outstanding balance × (annual rate / 365) × days elapsed
        since the previous entry (or the loan's activation date)."""
        for line in self:
            loan = line.loan_id
            if not loan:
                continue

            principal = (line.goods_released_quantity or 0.0) * loan.goods_unit_price

            if not loan.activation_date or not loan.annual_interest_rate:
                # Loan not yet active — no interest base to accrue against.
                line.interest = 0.0
                line.payment_amount = round(principal, 2)
                continue

            # Sort siblings safely: while a date is being typed/cleared it can be
            # momentarily False, and False can't be compared to a date — fall
            # back to the activation date (and finally today) so the sort never
            # breaks mid-edit.
            fallback_date = loan.activation_date or fields.Date.context_today(self)
            sorted_lines = loan.loan_line_ids.sorted(key=lambda r: r.date or fallback_date)

            daily_rate = loan.annual_interest_rate / 100.0 / 365.0
            prev_date = loan.activation_date
            outstanding = loan.bank_amount
            for l in sorted_lines:
                days = max((l.date - loan.activation_date).days, 0) if (l.date and loan.activation_date) else 0
                l_principal = (l.goods_released_quantity or 0.0) * loan.goods_unit_price
                interest = round(outstanding * daily_rate * days, 2)
                
                penalty = 0.0
                if l.date and loan.date_to and l.date > loan.date_to:
                    days_overdue = (l.date - loan.date_to).days
                    tier1_days = min(days_overdue, 30)
                    tier2_days = min(max(days_overdue - 30, 0), 30)
                    tier3_days = max(days_overdue - 60, 0)
                    
                    if tier1_days > 0 and loan.penalty_rate_tier1:
                        penalty += l_principal * (loan.penalty_rate_tier1 / 100.0 / 365.0) * tier1_days
                    if tier2_days > 0 and loan.penalty_rate_tier2:
                        penalty += l_principal * (loan.penalty_rate_tier2 / 100.0 / 365.0) * tier2_days
                    if tier3_days > 0 and loan.penalty_rate_tier3:
                        penalty += l_principal * (loan.penalty_rate_tier3 / 100.0 / 365.0) * tier3_days
                penalty = round(penalty, 2)
                
                if l == line:
                    line.interest = interest
                    line.penalty = penalty
                    line.payment_amount = round(l_principal + interest + penalty, 2)
                    break
                outstanding = max(outstanding - l_principal, 0.0)
                prev_date = l.date or prev_date

    # -------------------------------------------------------------------------
    # COMPUTE — outstanding after this line
    # -------------------------------------------------------------------------
    @api.depends('payment_amount', 'interest', 'penalty',
                 'loan_id.bank_amount', 'loan_id.loan_line_ids.payment_amount',
                 'loan_id.loan_line_ids.interest', 'loan_id.loan_line_ids.penalty')
    def _compute_outstanding_after(self):
        for line in self:
            loan = line.loan_id
            if not loan:
                line.outstanding_after = 0.0
                continue
            # Sum only principal portions (payment - interest) for all lines up to this one.
            # Fall back to date.min for any sibling whose date is momentarily unset
            # (e.g. being edited/cleared) so the sort never crashes mid-edit.
            principal_paid = 0.0
            for l in loan.loan_line_ids.sorted(key=lambda r: r.date or dt_date.min):
                principal_paid += (l.payment_amount or 0.0) - (l.interest or 0.0) - (l.penalty or 0.0)
                if l == line:
                    break
            line.outstanding_after = max(loan.bank_amount - principal_paid, 0.0)

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    @api.constrains('goods_released_quantity')
    def _check_goods_released_quantity(self):
        for line in self:
            if not line.goods_released_quantity or line.goods_released_quantity <= 0:
                raise ValidationError(_(
                    'Goods to Release (Qty) must be greater than zero on every '
                    'goods release entry — remove the empty/zero line before saving.'
                ))

    @api.constrains('goods_released_quantity', 'loan_id')
    def _check_release_within_bank_limit(self):
        """Prevent releasing goods when the bank loan is fully paid,
        or releasing more goods than the bank still holds."""
        for line in self:
            loan = line.loan_id
            if not loan:
                continue

            # Total goods released across all lines for this loan
            total_released = sum(
                l.goods_released_quantity for l in loan.loan_line_ids
            )
            # The bank controls only its percentage of the total goods
            bank_pct = loan.bank_coverage_percent / 100.0 if loan.bank_coverage_percent else 0.0
            bank_goods_total = round(loan.goods_quantity * bank_pct, 3)

            # Check 1: If outstanding is already 0, no more releases needed
            if loan.outstanding_loan <= 0 and len(loan.loan_line_ids) > 1:
                # Recalculate outstanding without current line to see if it was already 0
                total_penalty_paid = sum(l.penalty for l in loan.loan_line_ids if l.id != line.id)
                other_principal = sum(
                    (l.payment_amount or 0.0) - (l.interest or 0.0) - (l.penalty or 0.0)
                    for l in loan.loan_line_ids if l.id != line.id
                )
                was_outstanding = max(loan.bank_amount - other_principal, 0.0)
                if was_outstanding <= 0:
                    raise ValidationError(_(
                        'The bank loan is fully paid (Outstanding = 0). '
                        'The remaining goods in the warehouse are yours — '
                        'no further goods release entries are needed.'
                    ))

            # Check 2: Can't release more than the bank holds
            if total_released > bank_goods_total + 0.001:  # small tolerance for rounding
                raise ValidationError(_(
                    'You are trying to release %.3f units total, but the bank '
                    'only controls %.3f units (%.1f%% of %.3f). '
                    'You can release at most %.3f more units.'
                ) % (
                    total_released,
                    bank_goods_total,
                    loan.bank_coverage_percent,
                    loan.goods_quantity,
                    max(bank_goods_total - (total_released - line.goods_released_quantity), 0.0),
                ))

    # -------------------------------------------------------------------------
    # HOOKS — trigger recalculation when lines change
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # Recalculate interest for all affected loans
        loans = lines.mapped('loan_id')
        loans._recalculate_line_interest()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if 'goods_released_quantity' in vals or 'date' in vals:
            loans = self.mapped('loan_id')
            loans._recalculate_line_interest()
        return res