To effectively utilize the `l10n_ec_withhold` module, follow these essential steps:


1. **Journal, Agencies, and Emission Points Configuration:**

    For each journal, specify whether it will be used for withholding taxes on purchases or withholding taxes on sales. This can be configured in the journal settings.

    ```markdown
    - Navigate to Invoicing > Configuration > Accounting > Journals.
    - Set up relevant journals for electronic withholding.

2. **XML Code Configuration in Taxes:**
In order to align with Ecuadorian tax reporting requirements, the module introduces a feature where users must configure XML codes for taxes. This ensures that the generated tax reports comply with the specified XML standards mandated by local tax authorities.

3. **Tax Support Configuration:**
Users can now configure the "Tax Support" (tax justification) at both the line level and the invoice level. This flexibility allows businesses to provide detailed tax justifications for individual line items, enhancing transparency in tax documentation. Additionally, users have the option to set a global "Tax Support" at the invoice level, providing a comprehensive view of the tax justifications for the entire document.

4. **Position Fiscal Activation for Withholding Taxes:**
To enable the withholding tax functionality seamlessly, users need to activate it in the fiscal position settings for both the supplier and the company. This ensures that the system takes into account the specific fiscal requirements related to withholding taxes during transactions with the designated supplier.