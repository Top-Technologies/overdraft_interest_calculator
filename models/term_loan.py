import logging
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

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
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    def _compute_move_count(self):
        for record in self:
            moves = self.env['account.move'].search([
                ('term_loan_id', '=', record.id),
            ])
            record.move_count = len(moves.filtered(lambda m: m.move_type == 'entry'))
            record.bill_count = len(moves.filtered(lambda m: m.move_type == 'in_invoice'))

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

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
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
            payment_date = record.start_date + interval
            cumulative_interest = 0.0
            payment_number = 0
            lines_to_create = []

            while balance > 0.005:  # Small tolerance for rounding
                payment_number += 1

                # Interest for this period
                interest = round(balance * rate_per_period, 2)
                cumulative_interest += interest

                # Total payment (no extra payment on initial generation)
                total_pmt = scheduled_pmt
                if total_pmt > balance + interest:
                    total_pmt = round(balance + interest, 2)
                current_scheduled = min(scheduled_pmt, total_pmt)

                principal = round(total_pmt - interest, 2)
                ending_balance = round(balance - principal, 2)

                # Safety: ensure ending balance doesn't go negative
                if ending_balance < 0:
                    principal = round(balance, 2)
                    total_pmt = principal + interest
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

                # Safety limit: prevent infinite loops
                if payment_number > 1000:
                    _logger.warning(
                        "Term loan %s: schedule generation stopped at 1000 payments",
                        record.name
                    )
                    break

            # Batch create all lines
            self.env['term.loan.line'].create(lines_to_create)
            # Create disbursement journal entry
            record._create_disbursement_journal_entry()
            record.state = 'active'

    def action_recalculate_schedule(self):
        """Recalculate the amortization schedule using per-line extra payments."""
        for record in self:
            if record.state not in ('active', 'closed'):
                raise UserError(_('Schedule can only be recalculated for active or closed loans.'))

            lines = record.loan_line_ids.sorted('payment_number')
            if not lines:
                raise UserError(_('No schedule lines to recalculate. Generate the schedule first.'))

            ppy = int(record.payments_per_year)
            rate_per_period = record.annual_interest_rate / ppy
            scheduled_pmt = record.scheduled_payment

            balance = record.loan_amount
            cumulative_interest = 0.0

            for line in lines:
                if balance <= 0.005:
                    # Loan already paid off — zero out remaining lines
                    line.write({
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

                if ending_balance < 0:
                    principal = round(balance, 2)
                    total_pmt = principal + interest
                    ending_balance = 0.0

                line.write({
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
            unpaid = lines.filtered(lambda l: l.ending_balance > 0)
            if not unpaid:
                raise UserError(_('All payments have been scheduled. No unpaid lines found.'))

            line = unpaid[0]  # Next unpaid line
            partner = record.lender_name.bank_account_id.partner_id \
                if record.lender_name.bank_account_id else False

            # Bills must use a purchase journal, not a bank journal
            purchase_journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'),
                ('company_id', '=', self.env.company.id),
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

