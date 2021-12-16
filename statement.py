# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from io import StringIO
from decimal import Decimal
from itertools import groupby
from datetime import date

from trytond.pool import Pool, PoolMeta
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
