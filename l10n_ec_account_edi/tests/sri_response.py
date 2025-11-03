from datetime import datetime
from unittest.mock import create_autospec, patch

from zeep import Client

from odoo.addons.l10n_ec_account_edi.models.account_edi_format import AccountEdiFormat


# ==============================
# Respuestas de SRI ficticias
# ==============================
class DummyFactory:
    """Fábrica para generar objetos tipo Zeep para tests sin WSDL"""

    @staticmethod
    def mensaje(**kwargs):
        return kwargs

    @staticmethod
    def comprobante(**kwargs):
        return kwargs

    @staticmethod
    def respuestaSolicitud(**kwargs):
        return kwargs

    @staticmethod
    def autorizacion(**kwargs):
        return kwargs

    @staticmethod
    def respuestaComprobante(**kwargs):
        return kwargs


factory = DummyFactory()

sri_message_date = factory.mensaje(
    identificador="65",
    informacionAdicional="La fecha de emisión está fuera del rango de tolerancia "
    "[129600 minutos], o es mayor a la fecha del servidor",
    mensaje="FECHA EMISIÓN EXTEMPORANEA",
    tipo="ERROR",
)

validation_sri_response = factory.respuestaSolicitud(
    estado="RECIBIDA",
    comprobantes={
        "comprobante": [
            factory.comprobante(
                claveAcceso="DUMMY_ACCESS_KEY",
                mensajes={"mensaje": []},
            )
        ]
    },
)

validation_sri_response_returned = factory.respuestaSolicitud(
    estado="DEVUELTA",
    comprobantes={
        "comprobante": [
            factory.comprobante(
                claveAcceso="DUMMY_ACCESS_KEY",
                mensajes={"mensaje": [sri_message_date]},
            )
        ]
    },
)

auth_sri_response = factory.respuestaComprobante(
    claveAccesoConsultada="DUMMY_ACCESS_KEY",
    numeroComprobantes=1,
    autorizaciones={
        "autorizacion": [
            factory.autorizacion(
                estado="AUTORIZADO",
                numeroAutorizacion="DUMMY_ACCESS_KEY",
                fechaAutorizacion=datetime.now(),
                ambiente="PRUEBAS",
                comprobante="",
                mensajes={"mensaje": []},
            )
        ]
    },
)


# ==============================
# Mock del Cliente Zeep
# ==============================
def _mock_create_client(validation_response=None, auth_response=None):
    if validation_response is None:
        validation_response = validation_sri_response
    if auth_response is None:
        auth_response = auth_sri_response
    mock_client = create_autospec(Client)
    mock_client.service.validarComprobante.return_value = validation_response
    mock_client.service.autorizacionComprobante.return_value = auth_response
    return mock_client


def patch_service_sri(*args, **kwargs):
    """
    Decorador para reemplazar el cliente Zeep real por un mock en tests.
    """

    def wrapper(func):
        def patched(self, *func_args, **func_kwargs):
            validation_response = kwargs.get(
                "validation_response", validation_sri_response
            )
            auth_response = kwargs.get("auth_response", auth_sri_response)
            mock_client = _mock_create_client(validation_response, auth_response)
            with patch.object(
                AccountEdiFormat, "_l10n_ec_get_edi_ws_client", return_value=mock_client
            ):
                return func(self, *func_args, **func_kwargs)

        return patched

    if args and callable(args[0]):
        return wrapper(args[0])
    return wrapper
