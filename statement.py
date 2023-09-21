# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from io import StringIO
from decimal import Decimal
from itertools import groupby
from datetime import date

from trytond.model import Workflow, ModelView, ModelSQL, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.modules.account_statement.exceptions import ImportStatementError
from .credicoop_precargadas import Precargadas


class Statement(metaclass=PoolMeta):
    __name__ = 'account.statement'

    @property
    def lines_party(self):
        parties = [l.party for l in self.lines if l.party]
        if parties:
            return list(set(parties))[0]
        return None

    @classmethod
    def create_move(cls, statements):
        '''Supersedes create_move method
        from account_statement, to be able to group moves
        '''
        pool = Pool()
        Line = pool.get('account.statement.line')
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')

        moves = []
        for statement in statements:
            if statement.journal.group_moves_by_account:
                # Added code for custom grouping
                for key, lines in groupby(
                        statement.lines,
                        key=statement._group_by_account_period):
                    lines = list(lines)
                    key = dict(key)
                    key['description'] = statement.journal.name
                    move = statement._get_move_by_account_period(key)
                    moves.append((move, statement, lines))
            else:
                # Standard behavior
                for key, lines in groupby(
                        statement.lines, key=statement._group_key):
                    lines = list(lines)
                    key = dict(key)
                    move = statement._get_move(key)
                    moves.append((move, statement, lines))

        Move.save([m for m, _, _ in moves])

        to_write = []
        for move, _, lines in moves:
            to_write.append(lines)
            to_write.append({
                    'move': move.id,
                    })
        if to_write:
            Line.write(*to_write)

        move_lines = []
        for move, statement, lines in moves:
            amount = 0
            amount_second_currency = 0
            for line in lines:
                move_line = line.get_move_line()
                move_line.move = move
                amount += move_line.debit - move_line.credit
                if move_line.amount_second_currency:
                    amount_second_currency += move_line.amount_second_currency
                move_lines.append((move_line, line))

            move_line = statement._get_move_line(
                amount, amount_second_currency, lines)
            move_line.move = move
            move_lines.append((move_line, None))

        MoveLine.save([l for l, _ in move_lines])

        Line.reconcile(move_lines)
        return moves

    def _group_by_account_period(self, line):
        # Group by account and period
        key = (
            ('account', line.account),
            ('date', (line.date.year, line.date.month)),
            )
        return key

    def _get_move_by_account_period(self, key):
        pool = Pool()
        Move = pool.get('account.move')
        Period = pool.get('account.period')

        date_period = date(key['date'][0], key['date'][1], 1)
        period_id = Period.find(self.company.id, date=date_period)
        date_period = Period(period_id).end_date
        return Move(
            period=period_id,
            journal=self.journal.journal,
            date=date_period,
            origin=self,
            company=self.company,
            description=key['description'],
            )

    def _get_move_line(self, amount, amount_second_currency, lines):
        'Return counterpart Move Line for the amount'
        move = super()._get_move_line(amount, amount_second_currency, lines)
        if self.journal.account.party_required:
            move.party = self.lines_party
        return move


class ImportStatementStart(metaclass=PoolMeta):
    __name__ = 'account.statement.import.start'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        precargadas = ('credicoop_precargadas', 'Credicoop Precargadas')
        cls.file_format.selection.append(precargadas)


class ImportStatement(metaclass=PoolMeta):
    __name__ = 'account.statement.import'

    def parse_credicoop_precargadas(self, encoding='windows-1252'):
        file_ = self.start.file_
        if not isinstance(file_, str):
            file_ = file_.decode(encoding)
        file_ = StringIO(file_)
        precargadas = Precargadas(file_)
        for ccoop_statement in precargadas.statements:
            statement = self.precargadas_statement(ccoop_statement)
            debit_total = 0
            lines_count = 0
            origins = []
            for move in ccoop_statement.moves:
                # Only debits
                if move.debit == Decimal('0.00'):
                    continue
                if self.already_processed_move(move):
                    continue
                origins.extend(self.precargadas_origin(ccoop_statement, move))
                debit_total -= move.debit
                lines_count += 1

            statement.start_balance = 0
            statement.end_balance = debit_total
            statement.total_amount = debit_total
            statement.number_of_lines = lines_count
            statement.origins = origins
            yield statement

    def already_processed_move(self, move):
        pool = Pool()
        Origin = pool.get('account.statement.origin')

        origins = Origin.search([
            ('date', '=', move.date),
            ('number', '=', move.op_number),
            ])
        return origins and True or False

    def precargadas_statement(self, ccoop_statement):
        pool = Pool()
        Statement = pool.get('account.statement')
        Journal = pool.get('account.statement.journal')

        receiver = ccoop_statement.receiver
        card_number = ccoop_statement.card_number
        date_from = ccoop_statement.date_from
        date_to = ccoop_statement.date_to
        statement = Statement()
        statement.name = '%(receiver)s-%(card_number)s@(%(date_from)s/' \
            '%(date_to)s)' % {
                'receiver': receiver,
                'card_number': card_number,
                'date_from': date_from,
                'date_to': date_to,
                }
        statement.company = self.start.company
        statement.journal = Journal.get_by_bank_account(
            statement.company, card_number)
        if not statement.journal:
            raise ImportStatementError(
                'To import statement, you must create a journal for '
                'account "%(account)s".' % {'account': card_number})
        return statement

    def precargadas_origin(self, ccoop_statement, move):
        pool = Pool()
        Origin = pool.get('account.statement.origin')

        origin = Origin()
        origin.number = move.op_number
        origin.date = move.date
        origin.amount = move.debit * -1
        origin.party = self.precargadas_party(ccoop_statement)
        description = move.description1 and move.description1 + ' - ' or ''
        origin.description = description + move.description2
        origin.information = self.precargadas_information(ccoop_statement)
        return [origin]

    def precargadas_party(self, ccoop_statement):
        pool = Pool()
        Identifier = pool.get('party.identifier')

        identifiers = Identifier.search([
            ('type', '=', 'ar_tarjeta_precargada'),
            ('code', '=', ccoop_statement.card_number)
            ])
        if len(identifiers) == 1:
            return identifiers[0].party

    def precargadas_information(self, ccoop_statement):
        information = {}
        for name in ['card_number']:
            value = getattr(ccoop_statement, name)
            if value:
                information['credicoop_precargadas_' + name] = value
        return information


class PreloadedCardLoading(Workflow, ModelSQL, ModelView):
    'Preloaded Card Loading'
    __name__ = 'account.preloaded_card.loading'

    _states = {'readonly': Eval('state') != 'draft'}
    _depends = ['state']

    date = fields.Date('Date', required=True, select=True,
        states=_states, depends=_depends)
    description = fields.Char('Description',
        states=_states, depends=_depends)
    company = fields.Many2One('company.company', 'Company',
        required=True, select=True,
        states=_states, depends=_depends)
    journal = fields.Many2One('account.journal', 'Journal',
        required=True, select=True,
        context={'company': Eval('company', -1)},
        states=_states, depends=['state', 'company'])
    credit_account = fields.Many2One('account.account', 'Credit Account',
        required=True,
        domain=[
            ('type', '!=', None),
            ('closed', '!=', True),
            ('company', '=', Eval('company', 0)),
            ],
        states=_states, depends=['state', 'company'],
        help='Bank Accounting Account')
    debit_account = fields.Many2One('account.account', 'Debit Account',
        required=True,
        domain=[
            ('type', '!=', None),
            ('closed', '!=', True),
            ('company', '=', Eval('company', 0)),
            ],
        states=_states, depends=['state', 'company'],
        help='Party Accounting Account')
    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')
    total_amount = fields.Function(fields.Numeric('Total Amount',
        digits=(16, 2)), 'on_change_with_total_amount')
    lines = fields.One2Many('account.preloaded_card.loading.line',
        'card_loading', 'Lines',
        context={'company': Eval('company', -1)},
        states=_states, depends=['state', 'company'])
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
        ], 'State', readonly=True, select=True)
    move = fields.Many2One('account.move', 'Move', readonly=True)
    cancel_move = fields.Many2One('account.move', 'Cancel Move', readonly=True,
        states={'invisible': ~Eval('cancel_move')})

    del _states, _depends

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order[0] = ('date', 'DESC')
        cls._transitions |= set((
            ('draft', 'posted'),
            ('posted', 'cancelled'),
            ))
        cls._buttons.update({
            'post': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            'cancel': {
                'invisible': Eval('state') != 'posted',
                'depends': ['state'],
                },
            })

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_date():
        Date = Pool().get('ir.date')
        return Date.today()

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        if self.company:
            return self.company.currency.id

    @fields.depends('lines')
    def on_change_with_total_amount(self, name=None):
        total = Decimal(0)
        for line in self.lines:
            total += line.amount or Decimal(0)
        return total

    @classmethod
    def delete(cls, card_loadings):
        for card_loading in card_loadings:
            if card_loading.state != 'draft':
                raise UserError(gettext(
                    'account_statement_credicoop.msg_card_loading_delete'))
        super().delete(card_loadings)

    @classmethod
    @ModelView.button
    @Workflow.transition('posted')
    def post(cls, card_loadings):
        pool = Pool()
        Move = pool.get('account.move')

        moves = []
        for card_loading in card_loadings:
            move = card_loading.get_move()
            card_loading.move = move
            card_loading.save()
            moves.append(move)

        if moves:
            Move.save(moves)
            Move.post(moves)

    def get_move(self):
        pool = Pool()
        Period = pool.get('account.period')
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')

        accounting_date = self.date
        period_id = Period.find(self.company.id, date=accounting_date)

        move_lines = []
        for line in self.lines:
            move_line = MoveLine()
            move_line.amount_second_currency = None
            move_line.second_currency = None
            move_line.debit = line.amount
            move_line.credit = 0
            move_line.account = self.debit_account
            move_line.party = line.party
            move_line.maturity_date = self.date
            move_line.description = self.description
            move_lines.append(move_line)

        move_line = MoveLine()
        move_line.amount_second_currency = None
        move_line.second_currency = None
        move_line.debit = 0
        move_line.credit = self.total_amount
        move_line.account = self.credit_account
        move_line.maturity_date = self.date
        move_line.description = self.description
        move_lines.append(move_line)

        move = Move()
        move.journal = self.journal
        move.period = period_id
        move.date = accounting_date
        move.origin = self
        move.company = self.company
        move.description = self.description
        move.lines = move_lines
        return move

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, card_loadings):
        pool = Pool()
        Move = pool.get('account.move')

        cancel_moves = []
        for card_loading in card_loadings:
            if card_loading.move:
                move = card_loading.move.cancel()
                card_loading.cancel_move = move
                card_loading.save()
                cancel_moves.append(move)

        if cancel_moves:
            Move.save(cancel_moves)
            Move.post(cancel_moves)

    @classmethod
    @ModelView.button
    def export_file(cls, card_loadings):
        pass

    @classmethod
    def copy(cls, card_loadings, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('move', None)
        default.setdefault('cancel_move', None)
        return super().copy(card_loadings, default=default)


class PreloadedCardLoading2(metaclass=PoolMeta):
    __name__ = 'account.preloaded_card.loading'

    @fields.depends('credit_account', 'debit_account', 'journal', 'lines')
    def on_change_credit_account(self):
        self.add_lines()

    @fields.depends('credit_account', 'debit_account', 'journal', 'lines')
    def on_change_debit_account(self):
        self.add_lines()

    @fields.depends('credit_account', 'debit_account', 'journal', 'lines')
    def on_change_journal(self):
        self.add_lines()

    def add_lines(self):
        pool = Pool()
        Partner = pool.get('cooperative.partner')
        CardLoadingLine = pool.get('account.preloaded_card.loading.line')

        lines = []
        if (not self.credit_account or not self.debit_account or
                not self.journal):
            self.lines = lines
            return

        if self.lines:
            return

        partners = Partner.search([('status', '=', 'active')],
            order=[('file', 'ASC')])
        for partner in partners:
            line = CardLoadingLine()
            line.party = partner.party
            line.amount = Decimal(0)
            lines.append(line)

        self.lines = lines


class PreloadedCardLoadingLine(ModelSQL, ModelView):
    'Preloaded Card Loading Line'
    __name__ = 'account.preloaded_card.loading.line'

    card_loading = fields.Many2One('account.preloaded_card.loading',
        'Card Loading', required=True, ondelete='CASCADE')
    party = fields.Many2One('party.party', 'Party')
    card_number = fields.Char('Card Number')
    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')
    amount = fields.Numeric('Amount', required=True,
        digits=(16, 2))

    @fields.depends('card_loading', '_parent_card_loading.journal')
    def on_change_with_currency(self, name=None):
        if self.card_loading and self.card_loading.journal:
            return self.card_loading.journal.currency.id
