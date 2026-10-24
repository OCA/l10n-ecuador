The `l10n_ec_account_edi` module is a crucial component in the Odoo ecosystem, specifically tailored for businesses operating in Ecuador. This module facilitates Electronic Invoicing compliance with the requirements set forth by the Ecuadorian tax authorities. It streamlines the generation and management of electronic invoices, ensuring adherence to legal standards and promoting efficiency in billing processes.

## Features

1. **Electronic Invoice Generation:** The module enables the automatic generation of electronic invoices in compliance with the Ecuadorian tax regulations. This includes the incorporation of required data fields and formats mandated by the tax authorities.

2. **Digital Signature Integration:** `l10n_ec_account_edi` integrates digital signature capabilities into the electronic invoicing process. This ensures the authenticity and integrity of the generated electronic invoices, meeting the legal requirements for electronic documents.

3. **Automated Submission:** The module streamlines the submission process of electronic invoices to the tax authorities' systems. It automates the communication and transmission of invoice data, reducing manual intervention and minimizing errors.

4. **Real-time Validation:** Before submission, the module performs real-time validation checks to ensure that the generated electronic invoices comply with the current legal standards. This helps in identifying and rectifying issues proactively.

## Known issues

- The SRI authorization response field `numeroAutorizacion` normally equals
  the generated *clave de acceso*, so the module reuses the single
  `l10n_ec_xml_access_key` field instead of keeping a separate
  `l10n_ec_authorization_number` field. The SRI value is only persisted when
  it differs from the generated key (e.g. contingency). If a contingency flow
  ever returns a divergent authorization number, it overwrites the access key
  and that divergence is kept as a documented limitation.
