from datetime import datetime
from unittest.mock import create_autospec, patch

from zeep import Client
from zeep.transports import Transport

from odoo.addons.l10n_ec_account_edi.models.account_edi_format import (
    PRODUCTION_URL,
    AccountEdiFormat,
)

ws_url = PRODUCTION_URL.get("reception")
transport = Transport(timeout=30)
wsClient = Client(ws_url, transport=transport)
factory = wsClient.type_factory("ns0")

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

ws_url = PRODUCTION_URL.get("authorization")
wsClient = Client(ws_url, transport=transport)
factory = wsClient.type_factory("ns0")

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


def _mock_create_client(validation_response, auth_response):
    mock_client = create_autospec(Client)
    mock_client.service.validarComprobante.return_value = validation_response
    mock_client.service.autorizacionComprobante.return_value = auth_response
    return mock_client


def patch_service_sri(*args, **kwargs):
    """
    Change the Zeep Client to Mock
    so as not to consume SRI's webservices validarComprobante.

    Example usage
    - use default response(OK)

    @patch_service_sri
    def test_my_test(self)
        Your code

    - change default response(Returned)
    @patch_service_sri(validation_response=CustomResponse)
    def test_my_test(self)
        Your code

    :param validation_response: the response expected,
        if is None then use 'validation_sri_response'
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

    # Si el decorador se usa con un argumento (callable), devuelve el decorador aplicado
    if args and callable(args[0]):
        return wrapper(args[0])
    return wrapper
