from odoo import models, fields, api, _

class OverdraftCloseWizard(models.TransientModel):
    _name = 'overdraft.close.wizard'
    _description = 'Double Warning Wizard to Close Overdraft'

    overdraft_id = fields.Many2one('overdraft.interest', string='Overdraft', required=True)
    step = fields.Selection([('1', 'First Warning'), ('2', 'Final Warning')], default='1')

    def action_next_step(self):
        self.step = '2'
        return {
            'type': 'ir.actions.act_window',
            'name': _('Final Warning: Close Overdraft'),
            'res_model': 'overdraft.close.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm_close(self):
        self.overdraft_id.write({'state': 'closed'})
        return {'type': 'ir.actions.act_window_close'}
