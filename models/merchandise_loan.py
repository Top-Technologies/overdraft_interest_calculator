import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import date as dt_date

_logger = logging.getLogger(__name__)


class MerchandiseLoan(models.Model):
    _name = 'merchandise.loan'
    _description = 'Merchandise Loan'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin']
    _order = 'date_from desc, id desc'

    # -------------------------------------------------------------------------
    # DEFAULT HELPERS
    # -------------------------------------------------------------------------
    @api.model
    def _default_currency(self):
        return self.env.company.currency_id

    # -------------------------------------------------------------------------
    # FIELDS — Identity
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

    # -------------------------------------------------------------------------
    # FIELDS — Bank
    # -------------------------------------------------------------------------
    bank_journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        required=True,
        domain="[('type', '=', 'bank')]",
        tracking=True,
    )
    bank_id = fields.Many2one(
        'res.bank',
        string='Bank',
        related='bank_journal_id.bank_id',
        store=True,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Period and Currency
    # -------------------------------------------------------------------------
    date_from = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        tracking=True,
    )
    activation_date = fields.Date(
        string='Activation Date',
        readonly=True,
        copy=False,
        help='Date when the loan was activated. Interest accrues from this date.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=_default_currency,
        required=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Goods / Merchandise
    # -------------------------------------------------------------------------
    product_id = fields.Many2one(
        'product.product',
        string='Merchandise / Goods',
        required=True,
        tracking=True,
        help='The type of goods being financed',
    )
    goods_quantity = fields.Float(
        string='Total Goods Quantity',
        required=True,
        digits=(16, 3),
        tracking=True,
    )
    goods_unit_price = fields.Monetary(
        string='Unit Price',
        currency_field='currency_id',
        required=True,
        tracking=True,
        help='Cost price per unit of the financed goods.',
    )
    goods_selling_price = fields.Monetary(
        string='Selling Price (Unit)',
        currency_field='currency_id',
        tracking=True,
        help='Expected or actual selling price per unit of the financed goods, '
             'used to gauge margin against the actual (unit price + interest) cost.',
    )
    total_goods_value = fields.Monetary(
        string='Total Goods Value',
        compute='_compute_goods_value',
        store=True,
        currency_field='currency_id',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Storage Warehouse',
        required=True,
        tracking=True,
        help='Warehouse where goods are stored under bank control',
    )

    # Provided by analytic.mixin — relabelled for this business context.
    analytic_distribution = fields.Json(
        string='Business Unit / Department',
        help='The company business unit or department receiving and using this '
             'merchandise loan facility.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Trade & Merchandise Details
    # -------------------------------------------------------------------------
    product_category = fields.Selection([
        ('machinery', 'Machinery'),
        ('vehicles', 'Vehicles'),
        ('plastic_raw_materials', 'Plastic Raw Materials'),
        ('construction_materials', 'Construction Materials'),
        ('industrial_equipment', 'Industrial Equipment'),
        ('electronics', 'Electronics'),
        ('consumer_goods', 'Consumer Goods'),
        ('other', 'Other'),
    ], string='Product Category', tracking=True,
        help='Classification of the financed goods or merchandise.')
    import_document_type = fields.Selection([
        ('lc', 'Letter of Credit (LC)'),
        ('cad', 'Cash Against Documents (CAD)'),
        ('tt', 'Telegraphic Transfer (TT)'),
        ('shipping', 'Shipping Documents'),
        ('other', 'Other'),
    ], string='Import Document Type', tracking=True,
        help='Type of trade/import document associated with this transaction.')
    import_document_number = fields.Char(
        string='Import Document Number',
        tracking=True,
        help='Reference number of the trade or import document (LC, CAD, TT, '
             'or shipping documents).',
    )
    goods_description = fields.Text(
        string='Goods Description',
        tracking=True,
        help='Detailed description of the financed merchandise at product '
             'level: specifications, model, type, or quality.',
    )
    goods_location = fields.Selection([
        ('port', 'Port'),
        ('customs_terminal', 'Customs Terminal'),
        ('warehouse', 'Warehouse'),
        ('bonded_warehouse', 'Bonded Warehouse'),
        ('transit_area', 'Transit Area'),
        ('customer_site', 'Customer Site'),
    ], string='Goods Location', tracking=True,
        help='Current physical location of the financed goods.')
    sales_status = fields.Selection([
        ('unsold', 'Unsold'),
        ('reserved', 'Reserved'),
        ('partially_sold', 'Partially Sold'),
        ('sold', 'Sold'),
        ('slow_moving', 'Slow-Moving'),
        ('dead_stock', 'Dead Stock'),
    ], string='Sales Status', default='unsold', tracking=True,
        help='Current sales condition of the financed goods. "Dead Stock" flags goods '
             'that remain unsold/inactive beyond the acceptable holding period and carry '
             'higher repayment risk.')

    # Acceptable holding period (days) before unsold/slow-moving goods are treated
    # as dead-stock risk on the dashboard, even if not manually flagged.
    DEAD_STOCK_HOLDING_DAYS = 90

    days_held = fields.Integer(
        string='Days Held',
        compute='_compute_dead_stock_risk',
        help='Days elapsed since the loan was activated (or since the start date, '
             'if not yet activated).',
    )
    is_dead_stock_risk = fields.Boolean(
        string='Dead Stock Risk',
        compute='_compute_dead_stock_risk',
        help='True when goods are manually marked "Dead Stock", or remain Unsold/'
             'Slow-Moving beyond the %d-day acceptable holding period while the loan '
             'is active.' % DEAD_STOCK_HOLDING_DAYS,
    )

    @api.depends('activation_date', 'date_from', 'sales_status', 'state')
    def _compute_dead_stock_risk(self):
        today = fields.Date.context_today(self)
        for rec in self:
            start = rec.activation_date or rec.date_from
            rec.days_held = (today - start).days if start else 0
            rec.is_dead_stock_risk = rec.sales_status == 'dead_stock' or (
                rec.sales_status in ('unsold', 'slow_moving')
                and rec.state == 'active'
                and rec.days_held > rec.DEAD_STOCK_HOLDING_DAYS
            )

    # -------------------------------------------------------------------------
    # FIELDS — Loan Coverage (Company pays X% to bank, bank lends Y%)
    # -------------------------------------------------------------------------
    company_coverage_percent = fields.Float(
        string='Company Deposit (%)',
        default=30.0,
        required=True,
        digits=(5, 2),
        tracking=True,
        help='Percentage the company pays to the bank upfront (e.g. 30)',
    )
    bank_coverage_percent = fields.Float(
        string='Bank Loan (%)',
        compute='_compute_goods_value',
        store=True,
        digits=(5, 2),
        readonly=True,
    )
    company_amount = fields.Monetary(
        string='Company Deposit Amount',
        compute='_compute_goods_value',
        store=True,
        currency_field='currency_id',
    )
    bank_amount = fields.Monetary(
        string='Bank Loan Amount',
        compute='_compute_goods_value',
        store=True,
        currency_field='currency_id',
        help='Amount the bank lends — this is the loan to repay',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Interest Rates
    # -------------------------------------------------------------------------
    annual_interest_rate = fields.Float(
        string='Annual Interest Rate (%)',
        digits=(16, 6),
        required=True,
        tracking=True,
        help='Annual interest rate as a percentage (e.g. 16.5)',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Penalty Rates
    # -------------------------------------------------------------------------
    penalty_rate_tier1 = fields.Float(
        string='Penalty Rate — Days 1–30 (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied for every day in the first 30 days past the loan end date.',
    )
    penalty_rate_tier2 = fields.Float(
        string='Penalty Rate — Days 31–60 (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied for every day between 31 and 60 days past the loan end date.',
    )
    penalty_rate_tier3 = fields.Float(
        string='Penalty Rate — Days 60+ (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied for every day beyond 60 days past the loan end date.',
    )
    penalty_amount = fields.Monetary(
        string='Penalty Amount',
        compute='_compute_penalty',
        currency_field='currency_id',
        help='Penalty accrued on the outstanding bank loan amount, based on days past the loan end date.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Purpose & Collateral
    # -------------------------------------------------------------------------
    purpose = fields.Text(
        string='Purpose',
        tracking=True,
        help='Intended use of this merchandise loan (e.g. import of plastic raw materials, vehicle acquisition).',
    )
    collateral_document_ids = fields.Many2many(
        'ir.attachment',
        'merchandise_loan_collateral_attachment_rel',
        'loan_id',
        'attachment_id',
        string='Collateral Documents',
        help='Attach collateral documents such as import invoices, warehouse receipts, or guarantees.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Computed Totals
    # -------------------------------------------------------------------------
    total_paid = fields.Monetary(
        string='Total Paid',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_goods_released_qty = fields.Float(
        string='Total Goods Released (Qty)',
        compute='_compute_totals',
        store=True,
        digits=(16, 3),
        help='Total quantity of goods released from bank control via goods release entries.',
    )
    goods_held_qty = fields.Float(
        string='Goods Held by Bank (Qty)',
        compute='_compute_totals',
        store=True,
        digits=(16, 3),
        help='Quantity of goods still under bank control (bank\'s portion minus released).',
    )
    goods_owned_by_company = fields.Float(
        string='Goods Owned by Company (Qty)',
        compute='_compute_totals',
        store=True,
        digits=(16, 3),
        help='Quantity of goods the company owns outright (its deposit portion + '
             'goods freed after outstanding reaches zero).',
    )
    total_interest = fields.Monetary(
        string='Total Interest Accrued',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    outstanding_loan = fields.Monetary(
        string='Outstanding Loan',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    interest_per_unit = fields.Monetary(
        string='Interest per Unit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Total interest accrued ÷ total goods quantity',
    )
    actual_unit_cost = fields.Monetary(
        string='Actual Cost per Unit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Unit price + interest per unit',
    )
    margin_per_unit = fields.Monetary(
        string='Margin per Unit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Selling price minus actual cost per unit (unit price + interest per unit). '
             'Negative means the accrued interest has eroded the expected margin.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Payment Lines
    # -------------------------------------------------------------------------
    loan_line_ids = fields.One2many(
        'merchandise.loan.line',
        'loan_id',
        string='Goods Release Entries',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Accounting Links
    # -------------------------------------------------------------------------
    move_ids = fields.One2many(
        'account.move', 'merchandise_loan_id',
        string='Journal Entries',
    )
    bill_ids = fields.One2many(
        'account.move', 'merchandise_loan_id',
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
    # FIELDS — Account Links
    # -------------------------------------------------------------------------
    account_receivable_id = fields.Many2one(
        'account.account',
        string='Account Receivable',
        tracking=True,
        domain="[('account_type', '=', 'asset_receivable')]",
    )
    account_payable_id = fields.Many2one(
        'account.account',
        string='Account Payable',
        tracking=True,
        domain="[('account_type', '=', 'liability_payable')]",
    )
    income_account_id = fields.Many2one(
        'account.account',
        string='Income Account',
        tracking=True,
        domain="[('account_type', 'in', ('income', 'income_other'))]",
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        tracking=True,
        domain="[('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))]",
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    def _compute_move_count(self):
        for rec in self:
            moves = self.env['account.move'].search([
                ('merchandise_loan_id', '=', rec.id),
            ])
            rec.move_count = len(moves.filtered(lambda m: m.move_type == 'entry'))
            rec.bill_count = len(moves.filtered(lambda m: m.move_type == 'in_invoice'))

    @api.depends('goods_quantity', 'goods_unit_price', 'company_coverage_percent')
    def _compute_goods_value(self):
        for rec in self:
            total = rec.goods_quantity * rec.goods_unit_price
            rec.total_goods_value = total
            rec.bank_coverage_percent = 100.0 - rec.company_coverage_percent
            rec.company_amount = round(total * rec.company_coverage_percent / 100.0, 2)
            rec.bank_amount = round(total * rec.bank_coverage_percent / 100.0, 2)

    @api.depends(
        'date_to', 'bank_amount', 'outstanding_loan',
        'penalty_rate_tier1', 'penalty_rate_tier2', 'penalty_rate_tier3',
    )
    def _compute_penalty(self):
        """Tiered penalty on the outstanding bank loan amount, using date_to
        as the overdue anchor.

          • Days 1–30  → penalty_rate_tier1
          • Days 31–60 → penalty_rate_tier2
          • Days 60+   → penalty_rate_tier3
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.date_to or rec.date_to >= today or rec.outstanding_loan <= 0:
                rec.penalty_amount = 0.0
                continue

            days_overdue = (today - rec.date_to).days
            base = rec.outstanding_loan

            tier1_days = min(days_overdue, 30)
            tier2_days = min(max(days_overdue - 30, 0), 30)
            tier3_days = max(days_overdue - 60, 0)

            penalty = 0.0
            if tier1_days > 0 and rec.penalty_rate_tier1:
                penalty += base * (rec.penalty_rate_tier1 / 100.0 / 365.0) * tier1_days
            if tier2_days > 0 and rec.penalty_rate_tier2:
                penalty += base * (rec.penalty_rate_tier2 / 100.0 / 365.0) * tier2_days
            if tier3_days > 0 and rec.penalty_rate_tier3:
                penalty += base * (rec.penalty_rate_tier3 / 100.0 / 365.0) * tier3_days

            rec.penalty_amount = round(penalty, 2)

    @api.depends(
        'loan_line_ids.payment_amount',
        'loan_line_ids.goods_released_quantity',
        'loan_line_ids.interest',
        'loan_line_ids.penalty',
        'goods_quantity',
        'goods_unit_price',
        'goods_selling_price',
        'bank_amount',
        'company_coverage_percent',
    )
    def _compute_totals(self):
        for rec in self:
            lines = rec.loan_line_ids
            rec.total_paid = sum(l.payment_amount for l in lines)
            rec.total_goods_released_qty = sum(l.goods_released_quantity for l in lines)
            rec.total_interest = sum(l.interest for l in lines)

            # Outstanding = bank loan - principal portion paid (total_paid - total_interest - penalties)
            # We must exclude penalty from principal_paid since penalties don't reduce the loan principal.
            total_penalty_paid = sum(l.penalty for l in lines)
            principal_paid = rec.total_paid - rec.total_interest - total_penalty_paid
            rec.outstanding_loan = max(rec.bank_amount - principal_paid, 0.0)

            # --- Goods ownership based on bank's portion ---
            # The bank controls only its percentage of the total goods.
            # The company always owns its deposit portion outright.
            bank_pct = rec.bank_coverage_percent / 100.0 if rec.bank_coverage_percent else 0.0
            company_pct = rec.company_coverage_percent / 100.0 if rec.company_coverage_percent else 0.0
            bank_goods_total = round(rec.goods_quantity * bank_pct, 3)
            company_goods_base = round(rec.goods_quantity * company_pct, 3)

            if rec.outstanding_loan <= 0:
                # Loan fully paid — bank holds nothing, everything is the company's
                rec.goods_held_qty = 0.0
                rec.goods_owned_by_company = rec.goods_quantity - rec.total_goods_released_qty
            else:
                # Bank still holds goods = bank's portion minus what was released
                rec.goods_held_qty = max(bank_goods_total - rec.total_goods_released_qty, 0.0)
                # Company owns its base portion (the deposit share)
                rec.goods_owned_by_company = company_goods_base

            # Interest per unit — only RELEASED units have accrued any interest cost,
            # so this must be averaged over released quantity, not the full ordered quantity.
            if rec.total_goods_released_qty:
                rec.interest_per_unit = round(rec.total_interest / rec.total_goods_released_qty, 2)
            else:
                rec.interest_per_unit = 0.0

            # Actual cost per unit
            rec.actual_unit_cost = rec.goods_unit_price + rec.interest_per_unit

            # Margin per unit against the selling price
            rec.margin_per_unit = rec.goods_selling_price - rec.actual_unit_cost

    @api.constrains('annual_interest_rate')
    def _check_interest_rate(self):
        for record in self:
            if record.annual_interest_rate < 0:
                raise ValidationError(_('Interest rate cannot be negative.'))

    # -------------------------------------------------------------------------
    # HELPER — Recalculate interest on all lines
    # -------------------------------------------------------------------------
    def _recalculate_line_interest(self):
        """Recalculate daily interest on every line based on outstanding balance
        and days elapsed since the activation date to each entry date."""
        for rec in self:
            if not rec.activation_date:
                continue
            daily_rate = rec.annual_interest_rate / 100.0 / 365.0
            sorted_lines = rec.loan_line_ids.sorted(key=lambda r: r.date or rec.activation_date)
            prev_date = rec.activation_date
            outstanding = rec.bank_amount
            for line in sorted_lines:
                days = (line.date - rec.activation_date).days if line.date else 0
                days = max(days, 0)
                interest = round(outstanding * daily_rate * days, 2)
                principal = line.goods_released_quantity * rec.goods_unit_price
                
                penalty = 0.0
                if line.date and rec.date_to and line.date > rec.date_to:
                    days_overdue = (line.date - rec.date_to).days
                    tier1_days = min(days_overdue, 30)
                    tier2_days = min(max(days_overdue - 30, 0), 30)
                    tier3_days = max(days_overdue - 60, 0)
                    
                    if tier1_days > 0 and rec.penalty_rate_tier1:
                        penalty += principal * (rec.penalty_rate_tier1 / 100.0 / 365.0) * tier1_days
                    if tier2_days > 0 and rec.penalty_rate_tier2:
                        penalty += principal * (rec.penalty_rate_tier2 / 100.0 / 365.0) * tier2_days
                    if tier3_days > 0 and rec.penalty_rate_tier3:
                        penalty += principal * (rec.penalty_rate_tier3 / 100.0 / 365.0) * tier3_days
                penalty = round(penalty, 2)

                payment = round(principal + interest + penalty, 2)
                line.write({
                    'interest': interest,
                    'penalty': penalty,
                    'payment_amount': payment,
                })
                outstanding = max(outstanding - principal, 0.0)
                prev_date = line.date

    # -------------------------------------------------------------------------
    # SEQUENCE
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
                vals['name'] = self.env['ir.sequence'].next_by_code('merchandise.loan') or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft records can be submitted.'))
            rec.state = 'submitted'

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted records can be approved.'))
            rec.state = 'approved'

    def action_activate(self):
        """Activate the loan — sets activation date, interest accrues from here."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved loans can be activated.'))
            rec.activation_date = fields.Date.context_today(self)
            # Create disbursement journal entry
            rec._create_disbursement_journal_entry()
            rec.state = 'active'

    def action_reject(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted records can be rejected.'))
            rec.state = 'draft'

    def action_close(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError(_('Only active loans can be closed.'))
            rec.state = 'closed'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('submitted',):
                raise UserError(_(
                    'Only submitted records can be reset to draft. '
                    'Current state: %s'
                ) % rec.state)
            rec.state = 'draft'
            rec.activation_date = False

    # -------------------------------------------------------------------------
    # ACCOUNTING METHODS
    # -------------------------------------------------------------------------
    def _create_disbursement_journal_entry(self):
        """Create a journal entry for merchandise loan disbursement."""
        for rec in self:
            if not rec.account_payable_id:
                raise UserError(_(
                    'Please set Account Payable before activating.'
                ))
            bank_account = rec.bank_journal_id.default_account_id
            if not bank_account:
                raise UserError(_(
                    'The selected bank journal has no default account. '
                    'Please configure it in Accounting > Journals.'
                ))
            partner = rec.bank_journal_id.bank_account_id.partner_id \
                if rec.bank_journal_id.bank_account_id \
                else self.env.company.partner_id
            move_vals = {
                'journal_id': rec.bank_journal_id.id,
                'date': rec.activation_date or fields.Date.context_today(self),
                'ref': _('Merchandise Loan Disbursement: %s') % rec.name,
                'merchandise_loan_id': rec.id,
                'move_type': 'entry',
                'line_ids': [
                    (0, 0, {
                        'name': _('Loan Received: %s') % rec.name,
                        'account_id': bank_account.id,
                        'debit': rec.bank_amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': _('Loan Payable: %s') % rec.name,
                        'account_id': rec.account_payable_id.id,
                        'partner_id': partner.id,
                        'debit': 0.0,
                        'credit': rec.bank_amount,
                    }),
                ],
            }
            self.env['account.move'].create(move_vals)

    def action_create_bill(self):
        """Create a vendor bill for outstanding amount + interest."""
        for rec in self:
            if not rec.expense_account_id or not rec.account_payable_id:
                raise UserError(_(
                    'Please set both Expense Account and Account Payable.'
                ))
            if rec.outstanding_loan <= 0 and rec.total_interest <= 0:
                raise UserError(_('No outstanding amount to bill.'))

            partner = rec.bank_journal_id.bank_account_id.partner_id \
                if rec.bank_journal_id.bank_account_id else False

            # Bills must use a purchase journal, not a bank journal
            purchase_journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'),
                ('company_id', '=', rec.company_id.id),
            ], limit=1)
            if not purchase_journal:
                raise UserError(_('No purchase journal found. Please create one in Accounting > Configuration > Journals.'))

            bill_lines = []
            if rec.outstanding_loan > 0:
                bill_lines.append((0, 0, {
                    'name': _('Merchandise Loan Principal: %s') % rec.name,
                    'account_id': rec.account_payable_id.id,
                    'quantity': 1,
                    'price_unit': rec.outstanding_loan,
                }))
            if rec.total_interest > 0:
                bill_lines.append((0, 0, {
                    'name': _('Merchandise Loan Interest: %s') % rec.name,
                    'account_id': rec.expense_account_id.id,
                    'quantity': 1,
                    'price_unit': rec.total_interest,
                }))
            if rec.penalty_amount > 0:
                bill_lines.append((0, 0, {
                    'name': _('Merchandise Loan Penalty: %s') % rec.name,
                    'account_id': rec.expense_account_id.id,
                    'quantity': 1,
                    'price_unit': rec.penalty_amount,
                }))

            bill_vals = {
                'move_type': 'in_invoice',
                'journal_id': purchase_journal.id,
                'partner_id': partner.id if partner else False,
                'ref': _('Merchandise Loan Bill: %s') % rec.name,
                'invoice_date': fields.Date.context_today(self),
                'merchandise_loan_id': rec.id,
                'invoice_line_ids': bill_lines,
            }
            self.env['account.move'].create(bill_vals)

    # -------------------------------------------------------------------------
    # SMART BUTTON ACTIONS
    # -------------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        moves = self.env['account.move'].search([
            ('merchandise_loan_id', '=', self.id),
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
            ('merchandise_loan_id', '=', self.id),
            ('move_type', '=', 'in_invoice'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', bills.ids)],
        }                        