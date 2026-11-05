Importing a month of supplier XMLs:

1. Open **Invoicing ‣ SRI ‣ Import Supplier XML**.
2. Either attach the supplier `factura` XML, or type its 49-digit access
   key (`clave de acceso`). When both arrive, the file wins.
3. Press **Import**. The wizard creates one draft vendor bill and opens
   it: supplier resolved by RUC (auto-created under Imported Suppliers
   on first sight), SRI number as vendor reference, authorization key on
   the Ecuadorian authorization field, one bill line per XML detail
   with the purchase tax of its exact VAT rate, and the source XML
   attached to the bill.
4. Review taxes, sustento and amounts, then post the bill. An already
   imported invoice (same supplier + SRI number, or same authorization
   key) is refused instead of duplicated.

By access key:

1. Type the 49 digits and press **Import** with no file attached.
2. The wizard queries the public SRI `autorizacionComprobante` service
   (no certificate), unwraps the authorized `<comprobante>` and runs
   the same parser. When the SRI stays silent (recent authorizations
   only, no SLA), upload the file instead.
