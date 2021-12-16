# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.pool import PoolMeta


class PartyIdentifier(metaclass=PoolMeta):
    __name__ = 'party.identifier'

    @classmethod
    def __setup__(cls):
        super(PartyIdentifier, cls).__setup__()
        new_type = ('ar_tarjeta_precargada', 'Precargada')
        if new_type not in cls.type.selection:
            cls.type.selection.append(new_type)
