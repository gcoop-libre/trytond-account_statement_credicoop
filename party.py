# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.pool import PoolMeta


class PartyIdentifier(metaclass=PoolMeta):
    __name__ = 'party.identifier'

    @classmethod
    def get_types(cls):
        types = super().get_types()
        return types + [('ar_tarjeta_precargada', 'Precargada')]
