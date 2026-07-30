import logging
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class TermLoan(models.Model):
    _name = 'term.loan'
    _description = 'Term Loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    # -------------------------------------------------------------------------
    # DEFAULT HELPERS
    # -------------------------------------------------------------------------
    @api.model
    def _default_currency(self):
        return self.env.company.currency_id

    # -------------------------------------------------------------------------
    # FIELDS — Loan Input
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, copy=False)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )

    lender_name = fields.Many2one(
        'account.journal',
        string='Lender (Bank Journal)',
        required=True,
        tracking=True,
        domain="[('type', '=', 'bank')]",
        help='Select the bank journal for the lending institution',
    )
    bank_id = fields.Many2one(
        'res.bank',
        string='Bank',
        related='lender_name.bank_id',
        readonly=True,
    )
    loan_amount = fields.Monetary(
        string='Loan Amount',
        required=True,
        currency_field='currency_id',
        tracking=True,
        help='The total money borrowed from the bank',
    )
    annual_interest_rate = fields.Float(
        string='Annual Interest Rate',
        required=True,
        digits=(16, 6),
        tracking=True,
        help='Yearly cost of borrowing as a decimal (e.g. 0.1825 = 18.25%)',
    )
    loan_period_years = fields.Integer(
        string='Loan Period (Years)',
        required=True,
        tracking=True,
        help='How long the loan lasts in years',
    )
    payments_per_year = fields.Selection([
        ('12', 'Monthly (12)'),
        ('4', 'Quarterly (4)'),
        ('2', 'Semi-Annual (2)'),
        ('1', 'Annual (1)'),
    ], string='Payments Per Year', default='12', required=True, tracking=True,
       help='How many times you pay in one year')
    start_date = fields.Date(
        string='Start Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help='The date the loan officially begins',
    )
    grace_period_date = fields.Date(
        string='Grace Period End Date',
        tracking=True,
        help='Date communicated by the bank up to which the borrower is not '
             'required to make principal repayments. Interest may still '
             'accrue during this period.',
    )
    interest_accrue_from_grace = fields.Boolean(
        string='Interest Starts at Grace Period End',
        tracking=True,
        help='If checked, interest only starts accruing from the Grace '
             'Period End Date. If unchecked (default), interest starts '
             'accruing from the Start Date and any interest that builds up '
             'during the grace period is captured as a separate schedule line.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Disbursement
    # -------------------------------------------------------------------------
    disbursed_amount = fields.Monetary(
        string='Disbursed Amount',
        currency_field='currency_id',
        tracking=True,
        help='The portion of the approved loan amount that has already '
             'been released to the borrower.',
    )
    undisbursed_balance = fields.Monetary(
        string='Un-disbursed Balance',
        compute='_compute_undisbursed_balance',
        store=True,
        currency_field='currency_id',
        help='Approved Amount - Disbursed Amount: the remaining approved '
             'amount not yet released.',
    )
    # -------------------------------------------------------------------------
    # FIELDS — Account Links
    # -------------------------------------------------------------------------
    account_receivable_id = fields.Many2one(
        'account.account',
        string='Account Receivable',
        tracking=True,
        domain="[('account_type', '=', 'asset_receivable')]",
        help='Receivable account from Chart of Accounts',
    )
    account_payable_id = fields.Many2one(
        'account.account',
        string='Account Payable',
        tracking=True,
        domain="[('account_type', '=', 'liability_payable')]",
        help='Payable account from Chart of Accounts',
    )
    income_account_id = fields.Many2one(
        'account.account',
        string='Income Account',
        tracking=True,
        domain="[('account_type', 'in', ('income', 'income_other'))]",
        help='Income account from Chart of Accounts',
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        tracking=True,
        domain="[('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))]",
        help='Expense account from Chart of Accounts',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=_default_currency,
        required=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Purpose & Collateral
    # -------------------------------------------------------------------------
    purpose = fields.Text(
        string='Purpose',
        tracking=True,
        help='Intended use of the loan funds as approved by the lender.',
    )
    collateral_document_ids = fields.Many2many(
        'ir.attachment',
        'term_loan_collateral_attachment_rel',
        'loan_id',
        'attachment_id',
        string='Collateral Documents',
        help='Attach documents for pledged collateral (e.g. property deeds, vehicle certificates, guarantees).',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Schedule Lines
    # -------------------------------------------------------------------------
    loan_line_ids = fields.One2many(
        'term.loan.line',
        'loan_id',
        string='Amortization Schedule',
        copy=False,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Accounting Links
    # -------------------------------------------------------------------------
    move_ids = fields.One2many(
        'account.move', 'term_loan_id',
        string='Journal Entries',
    )
    bill_ids = fields.One2many(
        'account.move', 'term_loan_id',
        string='Bills',
        domain=[('move_type', '=', 'in_invoice')],
    )
    move_count = fields.Integer(
        compute='_compute_move_count',
        string='Journal Entry Count',
    )
    bill_count = fields.Integer(
        compute='_compute_move_count',
        string='Bill Count',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Computed Summary
    # -------------------------------------------------------------------------
    scheduled_payment = fields.Monetary(
        string='Scheduled Payment',
        compute='_compute_scheduled_payment',
        store=True,
        currency_field='currency_id',
        help='The regular payment amount per period (principal + interest)',
    )
    scheduled_num_payments = fields.Integer(
        string='Scheduled Number of Payments',
        compute='_compute_scheduled_num_payments',
        store=True,
        help='Total payments planned: years × payments per year',
    )
    actual_num_payments = fields.Integer(
        string='Actual Number of Payments',
        compute='_compute_actual_summary',
        store=True,
        help='How many payments were actually made (can be less with extra payments)',
    )
    total_interest = fields.Monetary(
        string='Total Interest',
        compute='_compute_actual_summary',
        store=True,
        currency_field='currency_id',
        help='Total money paid only as interest over the life of the loan',
    )
    total_early_payments = fields.Monetary(
        string='Total Early Payments',
        compute='_compute_actual_summary',
        store=True,
        currency_field='currency_id',
        help='Total extra payments made beyond the scheduled payment',
    )
    original_total_interest = fields.Monetary(
        string='Original Total Interest',
        compute='_compute_original_total_interest',
        store=True,
        currency_field='currency_id',
        help='Total interest that would be paid over the full loan life without extra payments',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Risk & Monitoring
    # -------------------------------------------------------------------------
    outstanding_principal = fields.Monetary(
        string='Outstanding Principal',
        compute='_compute_outstanding_principal',
        store=True,
        currency_field='currency_id',
        help='The unpaid portion of the original loan principal that '
             'remains due at this point in time.',
    )
    accrued_interest = fields.Monetary(
        string='Accrued Interest',
        compute='_compute_accrued_interest',
        currency_field='currency_id',
        help='Interest that has accumulated on the outstanding balance '
             'since the last payment date but has not yet been paid.',
    )
    overdue_amount = fields.Monetary(
        string='Overdue Amount',
        compute='_compute_overdue',
        currency_field='currency_id',
        help='Total unpaid amount (principal, interest, fees) that remains '
             'unpaid after its scheduled due date.',
    )
    days_past_due = fields.Integer(
        string='Days Past Due (DPD)',
        compute='_compute_overdue',
        help='Number of calendar days since the oldest unpaid scheduled '
             'payment became due. Used for delinquency tracking.',
    )
    is_delinquent = fields.Boolean(
        string='Delinquent',
        compute='_compute_overdue',
        help='True when this loan has at least one overdue unpaid payment.',
    )
    overdue_principal = fields.Monetary(
        string='Overdue Principal',
        compute='_compute_overdue',
        currency_field='currency_id',
        help='Total unpaid principal from installments past their due date.',
    )
    overdue_interest = fields.Monetary(
        string='Overdue Interest',
        compute='_compute_overdue',
        currency_field='currency_id',
        help='Total unpaid interest from installments past their due date.',
    )
    due_within_30_days = fields.Monetary(
        string='Due in 30 Days',
        compute='_compute_due_soon',
        currency_field='currency_id',
        help='Total repayments (principal and/or interest) scheduled to '
             'become due within the next 30 calendar days.',
    )
    due_within_90_days = fields.Monetary(
        string='Due in 90 Days',
        compute='_compute_due_soon',
        currency_field='currency_id',
        help='Total repayments scheduled to become due within the next '
             '90 calendar days.',
    )
    alert_level = fields.Selection([
        ('none', 'No Alert'),
        ('green', 'Green — Approaching Due'),
        ('yellow', 'Yellow — Delinquent'),
        ('red', 'Red — High Risk'),
        ('purple', 'Purple — Impaired'),
    ], string='Alert', compute='_compute_alert_level',
       help='Green: an installment is due within 15 days. '
            'Yellow: an installment is more than 1 day past due. '
            'Red: more than 60 days past due (high risk of default). '
            'Purple: more than 90 days past due (impaired loan).')
    alert_message = fields.Char(
        string='Alert Message',
        compute='_compute_alert_level',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Penalty
    # -------------------------------------------------------------------------
    penalty_rate_tier1 = fields.Float(
        string='Penalty Rate — Days 1–30 (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied to each overdue installment for every day '
             'in the first 30 days past its scheduled payment date.',
    )
    penalty_rate_tier2 = fields.Float(
        string='Penalty Rate — Days 31–60 (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied to each overdue installment for every day '
             'between 31 and 60 days past its scheduled payment date.',
    )
    penalty_rate_tier3 = fields.Float(
        string='Penalty Rate — Days 60+ (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied to each overdue installment for every day '
             'beyond 60 days past its scheduled payment date.',
    )
    penalty_amount = fields.Monetary(
        string='Penalty Amount',
        compute='_compute_penalty',
        currency_field='currency_id',
        help='Total penalty accrued across all overdue installments, using tiered daily rates.',
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    def _compute_move_count(self):
        for record in self:
            moves = self.env['account.move'].search([
                ('term_loan_id', '=', record.id),
            ])
            record.move_count = len(moves.filtered(lambda m: m.move_type == 'entry'))
            record.bill_count = len(moves.filtered(lambda m: m.move_type == 'in_invoice'))

    @api.depends('loan_amount', 'disbursed_amount')
    def _compute_undisbursed_balance(self):
        for record in self:
            record.undisbursed_balance = (record.loan_amount or 0.0) - (record.disbursed_amount or 0.0)

    @api.depends('loan_line_ids.beginning_balance', 'loan_line_ids.is_paid', 'disbursed_amount')
    def _compute_outstanding_principal(self):
        """Unpaid portion of principal still due right now (not the final
        ending balance of the schedule, which is the balance once the loan
        is fully repaid)."""
        for record in self:
            lines = record.loan_line_ids.sorted('payment_number')
            unpaid = lines.filtered(lambda l: not l.is_paid)
            if unpaid:
                record.outstanding_principal = unpaid[0].beginning_balance
            elif lines:
                record.outstanding_principal = 0.0
            else:
                record.outstanding_principal = record.disbursed_amount or 0.0

    @api.depends('loan_line_ids.is_paid', 'loan_line_ids.beginning_balance',
                 'loan_line_ids.payment_date', 'annual_interest_rate',
                 'payments_per_year', 'start_date', 'grace_period_date',
                 'interest_accrue_from_grace')
    def _compute_accrued_interest(self):
        """Interest built up on the outstanding balance since the last
        payment date (or the loan/grace start) but not yet paid."""
        today = fields.Date.context_today(self)
        for record in self:
            lines = record.loan_line_ids.sorted('payment_number')
            unpaid = lines.filtered(lambda l: not l.is_paid)
            if not unpaid or not record.annual_interest_rate:
                record.accrued_interest = 0.0
                continue

            next_line = unpaid[0]
            idx = list(lines).index(next_line)
            if idx > 0:
                period_start = lines[idx - 1].payment_date
            elif record.interest_accrue_from_grace and record.grace_period_date:
                period_start = record.grace_period_date
            else:
                period_start = record.start_date

            if not period_start or today <= period_start:
                record.accrued_interest = 0.0
                continue

            ppy = int(record.payments_per_year) if record.payments_per_year else 12
            period_days = 365.0 / ppy
            days_elapsed = min((today - period_start).days, period_days)
            daily_rate = record.annual_interest_rate / 365.0
            record.accrued_interest = round(next_line.beginning_balance * daily_rate * days_elapsed, 2)

    @api.depends('loan_line_ids.is_paid', 'loan_line_ids.payment_date', 'loan_line_ids.total_payment',
                 'loan_line_ids.principal', 'loan_line_ids.interest')
    def _compute_overdue(self):
        """Overdue amount and Days Past Due, based on unpaid lines whose
        due date has already passed."""
        today = fields.Date.context_today(self)
        for record in self:
            overdue_lines = record.loan_line_ids.filtered(
                lambda l: not l.is_paid and l.payment_date and l.payment_date < today
            )
            record.overdue_amount = sum(overdue_lines.mapped('total_payment'))
            record.overdue_principal = sum(overdue_lines.mapped('principal'))
            record.overdue_interest = sum(overdue_lines.mapped('interest'))
            record.is_delinquent = bool(overdue_lines)
            if overdue_lines:
                oldest = min(overdue_lines, key=lambda l: l.payment_date)
                record.days_past_due = (today - oldest.payment_date).days
            else:
                record.days_past_due = 0

    @api.depends('loan_line_ids.is_paid', 'loan_line_ids.payment_date', 'loan_line_ids.total_payment')
    def _compute_due_soon(self):
        """Repayments scheduled to fall due within the next 30 / 90 days
        (forward-looking cumulative buckets from today; does not include
        amounts already overdue)."""
        today = fields.Date.context_today(self)
        for record in self:
            upcoming = record.loan_line_ids.filtered(
                lambda l: not l.is_paid and l.payment_date and l.payment_date >= today
            )
            record.due_within_30_days = sum(
                upcoming.filtered(lambda l: (l.payment_date - today).days <= 30).mapped('total_payment')
            )
            record.due_within_90_days = sum(
                upcoming.filtered(lambda l: (l.payment_date - today).days <= 90).mapped('total_payment')
            )

    @api.depends(
        'loan_line_ids.is_paid', 'loan_line_ids.payment_date', 'loan_line_ids.total_payment',
        'loan_line_ids.penalty_amount',
        'penalty_rate_tier1', 'penalty_rate_tier2', 'penalty_rate_tier3',
    )
    def _compute_penalty(self):
        """Per-installment tiered penalty.

        Each overdue (unpaid and past due) line is penalised independently
        according to how many days *it specifically* has been overdue:
          • Days 1–30  → penalty_rate_tier1
          • Days 31–60 → penalty_rate_tier2
          • Days 60+   → penalty_rate_tier3
        The penalty base for each line is its total_payment (the unpaid
        installment amount). Results are summed to give penalty_amount.
        """
        for record in self:
            record.penalty_amount = sum(record.loan_line_ids.mapped('penalty_amount'))

    @api.depends('state', 'days_past_due', 'loan_line_ids.is_paid', 'loan_line_ids.payment_date')
    def _compute_alert_level(self):
        """Management alert level:
        - Green: an installment is due within the next 15 days.
        - Yellow: an installment is more than 1 day past due.
        - Red: more than 60 days past due (high risk of default).
        - Purple: more than 90 days past due (impaired loan).
        """
        today = fields.Date.context_today(self)
        for record in self:
            if record.state != 'active':
                record.alert_level = 'none'
                record.alert_message = ''
                continue

            dpd = record.days_past_due
            if dpd > 90:
                record.alert_level = 'purple'
                record.alert_message = _('Impaired loan: %s day(s) past due.') % dpd
            elif dpd > 60:
                record.alert_level = 'red'
                record.alert_message = _('High risk of default: %s day(s) past due.') % dpd
            elif dpd > 1:
                record.alert_level = 'yellow'
                record.alert_message = _('Delinquent: %s day(s) past due.') % dpd
            else:
                unpaid = record.loan_line_ids.filtered(lambda l: not l.is_paid and l.payment_date)
                upcoming = unpaid.filtered(
                    lambda l: l.payment_date >= today and (l.payment_date - today).days <= 15
                )
                if upcoming:
                    nearest = min(upcoming, key=lambda l: l.payment_date)
                    days_until = (nearest.payment_date - today).days
                    amount = nearest.total_due or nearest.total_payment
                    record.alert_level = 'green'
                    record.alert_message = _('Payment due in %s day(s) — Amount: %s %s') % (
                        days_until,
                        record.currency_id.symbol if record.currency_id else '',
                        '{:,.2f}'.format(amount),
                    )
                else:
                    record.alert_level = 'none'
                    record.alert_message = ''

    @api.depends('loan_amount', 'annual_interest_rate', 'loan_period_years', 'payments_per_year')
    def _compute_scheduled_payment(self):
        """Calculate the fixed payment using the PMT formula."""
        for record in self:
            if not (record.loan_amount and record.annual_interest_rate
                    and record.loan_period_years and record.payments_per_year):
                record.scheduled_payment = 0.0
                continue

            ppy = int(record.payments_per_year)
            rate_per_period = record.annual_interest_rate / ppy
            total_periods = record.loan_period_years * ppy

            if rate_per_period == 0:
                record.scheduled_payment = record.loan_amount / total_periods
            else:
                # PMT formula: P * r * (1+r)^n / ((1+r)^n - 1)
                compound = (1 + rate_per_period) ** total_periods
                record.scheduled_payment = round(
                    record.loan_amount * rate_per_period * compound / (compound - 1), 2
                )

    @api.depends('loan_period_years', 'payments_per_year')
    def _compute_scheduled_num_payments(self):
        for record in self:
            if record.loan_period_years and record.payments_per_year:
                record.scheduled_num_payments = record.loan_period_years * int(record.payments_per_year)
            else:
                record.scheduled_num_payments = 0

    @api.depends('loan_line_ids', 'loan_line_ids.interest', 'loan_line_ids.extra_payment')
    def _compute_actual_summary(self):
        for record in self:
            lines = record.loan_line_ids
            record.actual_num_payments = len(lines)
            record.total_interest = sum(l.interest for l in lines)
            record.total_early_payments = sum(l.extra_payment for l in lines)

    @api.depends('scheduled_payment', 'scheduled_num_payments', 'loan_amount')
    def _compute_original_total_interest(self):
        """Total interest over the full loan life assuming no extra payments."""
        for record in self:
            if record.scheduled_payment and record.scheduled_num_payments and record.loan_amount:
                record.original_total_interest = round(
                    (record.scheduled_payment * record.scheduled_num_payments) - record.loan_amount, 2
                )
            else:
                record.original_total_interest = 0.0

    @api.constrains('annual_interest_rate')
    def _check_interest_rate(self):
        for record in self:
            if record.annual_interest_rate < 0:
                raise ValidationError(_('Interest rate cannot be negative.'))

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('purpose'):
                raise UserError(_("Loan Purpose is compulsory when creating a new loan."))
            col = vals.get('collateral_document_ids')
            has_doc = False
            if col and isinstance(col, (list, tuple)):
                for cmd in col:
                    if isinstance(cmd, (list, tuple)):
                        if cmd[0] == 6 and cmd[2]:
                            has_doc = True
                        elif cmd[0] in (4, 0, 1, 2):
                            has_doc = True
            if not has_doc:
                raise UserError(_("At least one Collateral Document must be attached when creating a new loan."))

            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('term.loan')
                    or 'New'
                )
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------------------------
    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft records can be submitted.'))
            record.state = 'submitted'

    def action_approve(self):
        for record in self:
            if record.state != 'submitted':
                raise UserError(_('Only submitted records can be approved.'))
            record.state = 'approved'

    def action_reject(self):
        for record in self:
            if record.state != 'submitted':
                raise UserError(_('Only submitted records can be rejected.'))
            record.state = 'rejected'

    def action_reset_to_draft(self):
        for record in self:
            if record.state not in ('rejected', 'submitted'):
                raise UserError(_(
                    'Only rejected or submitted records can be reset to draft.'
                ))
            # Clear existing schedule lines when resetting
            record.loan_line_ids.unlink()
            record.state = 'draft'

    def action_close(self):
        for record in self:
            if record.state != 'active':
                raise UserError(_('Only active loans can be closed.'))
            record.state = 'closed'

    # -------------------------------------------------------------------------
    # SCHEDULE GENERATION
    # -------------------------------------------------------------------------
    def action_generate_schedule(self):
        """Generate the amortization schedule and move to active state."""
        for record in self:
            if record.state != 'approved':
                raise UserError(_('Schedule can only be generated for approved loans.'))

            # Validate inputs
            if record.loan_amount <= 0:
                raise UserError(_('Loan amount must be greater than zero.'))
            if record.annual_interest_rate <= 0:
                raise UserError(_('Annual interest rate must be greater than zero.'))
            if record.loan_period_years <= 0:
                raise UserError(_('Loan period must be greater than zero.'))
            if record.grace_period_date and record.grace_period_date < record.start_date:
                raise UserError(_('Grace period end date cannot be before the loan start date.'))

            # Clear existing lines
            record.loan_line_ids.unlink()

            ppy = int(record.payments_per_year)
            rate_per_period = record.annual_interest_rate / ppy
            scheduled_pmt = record.scheduled_payment

            # Calculate the payment interval
            if ppy == 12:
                interval = relativedelta(months=1)
            elif ppy == 4:
                interval = relativedelta(months=3)
            elif ppy == 2:
                interval = relativedelta(months=6)
            else:
                interval = relativedelta(years=1)

            balance = record.loan_amount
            cumulative_interest = 0.0
            payment_number = 0
            lines_to_create = []

            # ---------------------------------------------------------------
            # Grace period handling
            # ---------------------------------------------------------------
            # A grace period defers principal repayment. Whether interest
            # accrues during that window depends on interest_accrue_from_grace:
            #   - Unchecked (default): interest accrues from start_date and
            #     is captured as a standalone interest-only line (Pmt. #0)
            #     dated at the grace period end.
            #   - Checked: interest itself only starts at the grace period
            #     end date, so the amortization simply begins there.
            has_grace = bool(
                record.grace_period_date and record.grace_period_date > record.start_date
            )
            anchor_date = record.start_date

            if has_grace:
                if record.interest_accrue_from_grace:
                    anchor_date = record.grace_period_date
                else:
                    grace_days = (record.grace_period_date - record.start_date).days
                    daily_rate = record.annual_interest_rate / 365.0
                    grace_interest = round(balance * daily_rate * grace_days, 2)
                    cumulative_interest += grace_interest
                    lines_to_create.append({
                        'loan_id': record.id,
                        'payment_number': 0,
                        'payment_date': record.grace_period_date,
                        'beginning_balance': round(balance, 2),
                        'scheduled_payment': grace_interest,
                        'extra_payment': 0.0,
                        'total_payment': grace_interest,
                        'interest': grace_interest,
                        'principal': 0.0,
                        'ending_balance': round(balance, 2),
                        'cumulative_interest': round(cumulative_interest, 2),
                    })
                    anchor_date = record.grace_period_date

            payment_date = anchor_date + interval

            # Use a definite loop of exactly `scheduled_num_payments`
            # periods (years x payments-per-year) instead of an open-ended
            # "while balance > tolerance" loop. On large loan amounts,
            # rounding the fixed payment to cents at every period can leave
            # a residual of a few cents after the intended final payment
            # (e.g. $0.05 on a $50M loan) — that residual is bigger than a
            # fixed half-cent tolerance, so the old loop kept going and
            # generated a phantom extra installment. Forcing the last
            # period to fully clear the balance avoids that.
            total_scheduled_payments = int(record.loan_period_years) * ppy

            for i in range(1, total_scheduled_payments + 1):
                if balance <= 0.005:
                    break

                payment_number += 1
                is_last_period = (i == total_scheduled_payments)

                # Interest for this period
                interest = round(balance * rate_per_period, 2)
                cumulative_interest += interest

                if is_last_period:
                    # Force the final installment to fully clear the balance.
                    total_pmt = round(balance + interest, 2)
                else:
                    # Total payment (no extra payment on initial generation)
                    total_pmt = scheduled_pmt
                    if total_pmt > balance + interest:
                        total_pmt = round(balance + interest, 2)
                current_scheduled = min(scheduled_pmt, total_pmt)

                principal = round(total_pmt - interest, 2)
                ending_balance = round(balance - principal, 2)

                # Safety: ensure ending balance doesn't go negative, and
                # always fully close the balance on the final period.
                if is_last_period or ending_balance < 0:
                    principal = round(balance, 2)
                    total_pmt = round(principal + interest, 2)
                    current_scheduled = min(scheduled_pmt, total_pmt)
                    ending_balance = 0.0

                lines_to_create.append({
                    'loan_id': record.id,
                    'payment_number': payment_number,
                    'payment_date': payment_date,
                    'beginning_balance': round(balance, 2),
                    'scheduled_payment': round(current_scheduled, 2),
                    'extra_payment': 0.0,
                    'total_payment': round(total_pmt, 2),
                    'interest': interest,
                    'principal': round(principal, 2),
                    'ending_balance': ending_balance,
                    'cumulative_interest': round(cumulative_interest, 2),
                })

                balance = ending_balance
                payment_date += interval

            # Batch create all lines
            self.env['term.loan.line'].sudo().create(lines_to_create)
            # Create disbursement journal entry
            record._create_disbursement_journal_entry()
            if not record.disbursed_amount:
                record.disbursed_amount = record.loan_amount
            record.state = 'active'

    def action_recalculate_schedule(self):
        """Recalculate the amortization schedule using per-line extra payments."""
        for record in self:
            if record.state not in ('active', 'closed'):
                raise UserError(_('Schedule can only be recalculated for active or closed loans.'))

            lines = record.loan_line_ids.sorted('payment_number')
            if not lines:
                raise UserError(_('No schedule lines to recalculate. Generate the schedule first.'))

            ppy = int(record.payments_per_year) if record.payments_per_year else 12
            rate_per_period = record.annual_interest_rate / ppy
            scheduled_pmt = record.scheduled_payment

            balance = record.loan_amount
            cumulative_interest = 0.0

            # The grace-period interest-only line (Pmt. #0), if any, is left
            # untouched — it doesn't amortize principal — but its interest
            # still counts toward the running cumulative interest total.
            grace_line = lines.filtered(lambda l: l.payment_number == 0)
            if grace_line:
                cumulative_interest += grace_line.interest
            regular_lines = lines.filtered(lambda l: l.payment_number > 0)
            last_line = regular_lines[-1] if regular_lines else None

            for line in regular_lines:
                is_last_line = bool(last_line) and line.id == last_line.id

                if balance <= 0.005:
                    # Loan already paid off — zero out remaining lines
                    line.sudo().write({
                        'beginning_balance': 0.0,
                        'scheduled_payment': 0.0,
                        'total_payment': 0.0,
                        'interest': 0.0,
                        'principal': 0.0,
                        'ending_balance': 0.0,
                        'cumulative_interest': round(cumulative_interest, 2),
                    })
                    continue

                interest = round(balance * rate_per_period, 2)
                cumulative_interest += interest

                extra_pmt = line.extra_payment or 0.0

                if is_last_line:
                    # Force the final installment to fully clear the balance
                    # so rounding drift doesn't leave a stray cent-level
                    # residual on the loan.
                    total_pmt = round(balance + interest, 2)
                    current_scheduled = min(scheduled_pmt, total_pmt)
                else:
                    total_pmt = scheduled_pmt + extra_pmt
                    # Cap at remaining balance + interest
                    if total_pmt > balance + interest:
                        total_pmt = round(balance + interest, 2)
                        if total_pmt < scheduled_pmt:
                            current_scheduled = total_pmt
                        else:
                            current_scheduled = scheduled_pmt
                    else:
                        current_scheduled = scheduled_pmt

                principal = round(total_pmt - interest, 2)
                ending_balance = round(balance - principal, 2)

                if is_last_line or ending_balance < 0:
                    principal = round(balance, 2)
                    total_pmt = round(principal + interest, 2)
                    ending_balance = 0.0

                line.sudo().write({
                    'beginning_balance': round(balance, 2),
                    'scheduled_payment': round(current_scheduled, 2),
                    'total_payment': round(total_pmt, 2),
                    'interest': interest,
                    'principal': round(principal, 2),
                    'ending_balance': ending_balance,
                    'cumulative_interest': round(cumulative_interest, 2),
                })

                balance = ending_balance

    # -------------------------------------------------------------------------
    # ACCOUNTING METHODS
    # -------------------------------------------------------------------------
    def _create_disbursement_journal_entry(self):
        """Create a journal entry for loan disbursement."""
        for record in self:
            if not record.account_payable_id:
                raise UserError(_(
                    'Please set Account Payable before generating the schedule.'
                ))
            # Get the bank journal's default debit account
            bank_account = record.lender_name.default_account_id
            if not bank_account:
                raise UserError(_(
                    'The selected bank journal has no default account. '
                    'Please configure it in Accounting > Journals.'
                ))
            partner = record.lender_name.bank_account_id.partner_id \
                if record.lender_name and record.lender_name.bank_account_id \
                else record.company_id.partner_id
            move_vals = {
                'journal_id': record.lender_name.id,
                'date': record.start_date,
                'ref': _('Loan Disbursement: %s') % record.name,
                'term_loan_id': record.id,
                'move_type': 'entry',
                'line_ids': [
                    (0, 0, {
                        'name': _('Loan Received: %s') % record.name,
                        'account_id': bank_account.id,
                        'debit': record.loan_amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': _('Loan Payable: %s') % record.name,
                        'account_id': record.account_payable_id.id,
                        'partner_id': partner.id,
                        'debit': 0.0,
                        'credit': record.loan_amount,
                    }),
                ],
            }
            self.env['account.move'].create(move_vals)

    def action_create_bill(self):
        """Create a vendor bill for the next unpaid payment."""
        for record in self:
            if not record.expense_account_id or not record.account_payable_id:
                raise UserError(_(
                    'Please set both Expense Account and Account Payable.'
                ))

            # Find unpaid lines (ending_balance > 0)
            lines = record.loan_line_ids.sorted('payment_number')
            unpaid = lines.filtered(lambda l: not l.is_paid)
            if not unpaid:
                raise UserError(_('All payments have been scheduled. No unpaid lines found.'))

            line = unpaid[0]  # Next unpaid line
            partner = record.lender_name.bank_account_id.partner_id \
                if record.lender_name.bank_account_id else False

            # Bills must use a purchase journal, not a bank journal
            purchase_journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'),
                ('company_id', '=', record.company_id.id),
            ], limit=1)
            if not purchase_journal:
                raise UserError(_('No purchase journal found. Please create one in Accounting > Configuration > Journals.'))

            bill_vals = {
                'move_type': 'in_invoice',
                'journal_id': purchase_journal.id,
                'partner_id': partner.id if partner else False,
                'ref': _('Loan Payment #%s: %s') % (line.payment_number, record.name),
                'invoice_date': line.payment_date,
                'term_loan_id': record.id,
                'invoice_line_ids': [
                    (0, 0, {
                        'name': _('Principal Payment #%s') % line.payment_number,
                        'account_id': record.account_payable_id.id,
                        'quantity': 1,
                        'price_unit': line.principal,
                    }),
                    (0, 0, {
                        'name': _('Interest Payment #%s') % line.payment_number,
                        'account_id': record.expense_account_id.id,
                        'quantity': 1,
                        'price_unit': line.interest,
                    }),
                ],
            }
            self.env['account.move'].create(bill_vals)

    # -------------------------------------------------------------------------
    # SMART BUTTON ACTIONS
    # -------------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        moves = self.env['account.move'].search([
            ('term_loan_id', '=', self.id),
            ('move_type', '=', 'entry'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entries'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
        }

    def action_view_bills(self):
        self.ensure_one()
        bills = self.env['account.move'].search([
            ('term_loan_id', '=', self.id),
            ('move_type', '=', 'in_invoice'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', bills.ids)],
        }

    def action_record_payment(self):
        """Open the extra payment wizard popup."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Extra Payment'),
            'res_model': 'term.loan.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_loan_id': self.id,
            },
        }