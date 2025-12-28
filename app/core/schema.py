from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.enums import DocumentType


@dataclass(frozen=True)
class FieldSchema:
    key: str
    required: bool
    label: str
    dtype: str = "string"
    fmt: Optional[str] = None
    anchors: tuple[str, ...] = ()
    children: Dict[str, "FieldSchema"] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentSchema:
    doc_type: DocumentType
    fields: Dict[str, FieldSchema]

    @property
    def required_keys(self) -> List[str]:
        return [key for key, schema in self.fields.items() if schema.required]


def make_field(
    key: str,
    label: str,
    *,
    required: bool = False,
    fmt: Optional[str] = None,
    dtype: str = "string",
    anchors: tuple[str, ...] = (),
    children: Optional[Dict[str, FieldSchema]] = None,
) -> FieldSchema:
    return FieldSchema(
        key=key,
        required=required,
        label=label,
        dtype=dtype,
        fmt=fmt,
        anchors=anchors,
        children=children or {},
    )


PRODUCT_ITEM_BASE_FIELDS: Dict[str, FieldSchema] = {
    "name_product": make_field("name_product", "Product Name"),
    "latin_name": make_field("latin_name", "Latin Name"),
    "size_product": make_field("size_product", "Product Size"),
    "unit_box": make_field("unit_box", "Units per Box"),
    "packages": make_field("packages", "Packages"),
    "net_weight": make_field("net_weight", "Net Weight"),
    "gross_weight": make_field("gross_weight", "Gross Weight"),
    "price_per_unit": make_field("price_per_unit", "Price per Unit"),
    "total_price": make_field("total_price", "Total Price"),
}


def build_products_field(
    *,
    extra_fields: Optional[Dict[str, FieldSchema]] = None,
    label: str = "Products",
) -> FieldSchema:
    children = dict(PRODUCT_ITEM_BASE_FIELDS)
    if extra_fields:
        children.update(extra_fields)
    product_template = make_field(
        "product",
        "Product Item",
        children={field_key: field_schema for field_key, field_schema in children.items()},
    )
    return make_field(
        "products",
        label,
        children={"product_template": product_template},
    )


def build_products_template(*, children: Dict[str, FieldSchema], label: str = "Products") -> FieldSchema:
    """Build a products field whose product row contains exactly the provided children."""
    product_template = make_field(
        "product",
        "Product Item",
        children=children,
    )
    return make_field("products", label, children={"product_template": product_template})


EXPORT_DECLARATION_SCHEMA = DocumentSchema(
    doc_type=DocumentType.EXPORT_DECLARATION,
    fields={
        "export_declaration_no": make_field(
            "export_declaration_no",
            "Declaration Number",
            required=True,
            fmt=r"^[A-Z0-9-]+$",
            anchors=("DECLARATION", "NO", "NUMBER"),
        ),
        "export_declaration_date": make_field(
            "export_declaration_date",
            "Declaration Date",
            required=True,
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
            anchors=("DATE", "DECLARATION"),
        ),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "invoice_date": make_field("invoice_date", "Invoice Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "country_of_origin": make_field(
            "country_of_origin",
            "Country of Origin",
            required=True,
            fmt=r"^[A-Z]{2,3}$",
            anchors=("COUNTRY", "ORIGIN"),
        ),
        "producer": make_field("producer", "Producer"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "exporter": make_field("exporter", "Exporter"),
        "incoterms": make_field("incoterms", "Incoterms", fmt=r"^[A-Z]{3}$"),
        # Added to align with docs_json_2
        "proforma_no": make_field("proforma_no", "Proforma Number"),
        "HS_code": make_field("HS_code", "HS Code"),
        "total_price": make_field("total_price", "Total Price"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "price_per_unit": make_field("price_per_unit", "Price per Unit"),
                "total_price": make_field("total_price", "Total Price"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
            }
        ),
    },
)


INVOICE_SCHEMA = DocumentSchema(
    doc_type=DocumentType.INVOICE,
    fields={
        "invoice_no": make_field("invoice_no", "Invoice Number", required=True),
        "invoice_date": make_field(
            "invoice_date",
            "Invoice Date",
            required=True,
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "buyer": make_field("buyer", "Buyer", required=True),
        "seller": make_field("seller", "Seller", required=True),
        "producer": make_field("producer", "Producer"),
        "incoterms": make_field("incoterms", "Incoterms", fmt=r"^[A-Z]{3}$"),
        "terms_of_payment": make_field("terms_of_payment", "Terms of Payment"),
        "bank_details": make_field("bank_details", "Bank Details"),
        "proforma_no": make_field("proforma_no", "Proforma Number"),
        "container_no": make_field("container_no", "Container Number"),
        # Added to align with docs_json_2
        "HS_code": make_field("HS_code", "HS Code"),
        "total_price": make_field("total_price", "Total Price", required=True),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "price_per_unit": make_field("price_per_unit", "Price per Unit"),
                "total_price": make_field("total_price", "Total Price"),
            }
        ),
    },
)


PACKING_LIST_SCHEMA = DocumentSchema(
    doc_type=DocumentType.PACKING_LIST,
    fields={
        "packing_list_date": make_field(
            "packing_list_date",
            "Packing List Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "net_weight_with_glaze": make_field("net_weight_with_glaze", "Net Weight with Glaze"),
                "net_weight_with_ice": make_field("net_weight_with_ice", "Net Weight with Ice"),
                "net_weight_with_glaze_and_pack": make_field("net_weight_with_glaze_and_pack", "Net Weight with Glaze and Pack"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
                "price_per_unit": make_field("price_per_unit", "Price per Unit"),
                "total_price": make_field("total_price", "Total Price"),
                "factory_number": make_field("factory_number", "Factory Number"),
                "date_of_production": make_field("date_of_production", "Date of Production"),
            }
        ),
        "producer": make_field("producer", "Producer"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
    },
)


BILL_OF_LANDING_SCHEMA = DocumentSchema(
    doc_type=DocumentType.BILL_OF_LANDING,
    fields={
        "bill_of_landing_date": make_field(
            "bill_of_landing_date",
            "Bill of Landing Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "bill_of_landing_number": make_field("bill_of_landing_number", "Bill of Landing Number"),
        "exporter": make_field("exporter", "Exporter"),
        "destination": make_field("destination", "Destination"),
        "packages": make_field("packages", "Packages"),
        "net_weight": make_field("net_weight", "Net Weight"),
        "gross_weight": make_field("gross_weight", "Gross Weight"),
        "vessel": make_field("vessel", "Vessel"),
        "container_no": make_field("container_no", "Container Number"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "importer": make_field("importer", "Importer"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "commodity_code": make_field("commodity_code", "Commodity Code"),
        "size_product": make_field("size_product", "Product Size"),
    },
)


PRICE_LIST_1_SCHEMA = DocumentSchema(
    doc_type=DocumentType.PRICE_LIST_1,
    fields={
        "price_list_1_date": make_field(
            "price_list_1_date",
            "Price List 1 Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "producer": make_field("producer", "Producer"),
        "incoterms": make_field("incoterms", "Incoterms", fmt=r"^[A-Z]{3}$"),
        "seller": make_field("seller", "Seller"),
        "valid_till": make_field("valid_till", "Valid Till"),
        # Added to align with docs_json_2
        "HS_code": make_field("HS_code", "HS Code"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "price_per_unit": make_field("price_per_unit", "Price per Unit"),
                "total_price": make_field("total_price", "Total Price"),
            }
        ),
    },
)


PRICE_LIST_2_SCHEMA = DocumentSchema(
    doc_type=DocumentType.PRICE_LIST_2,
    fields={
        "price_list_2_date": make_field(
            "price_list_2_date",
            "Price List 2 Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "producer": make_field("producer", "Producer"),
        "incoterms": make_field("incoterms", "Incoterms", fmt=r"^[A-Z]{3}$"),
        "seller": make_field("seller", "Seller"),
        "valid_till": make_field("valid_till", "Valid Till"),
        # Added to align with docs_json_2
        "HS_code": make_field("HS_code", "HS Code"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "price_per_KG": make_field("price_per_KG", "Price per KG"),
                "total_price": make_field("total_price", "Total Price"),
            }
        ),
    },
)


QUALITY_CERTIFICATE_SCHEMA = DocumentSchema(
    doc_type=DocumentType.QUALITY_CERTIFICATE,
    fields={
        "quality_certificate_date": make_field(
            "quality_certificate_date",
            "Quality Certificate Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "date_of_production": make_field("date_of_production", "Date of Production"),
            }
        ),
        "container_no": make_field("container_no", "Container Number"),
        "vessel": make_field("vessel", "Vessel"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
    },
)


CERTIFICATE_OF_ORIGIN_SCHEMA = DocumentSchema(
    doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
    fields={
        "certificate_of_origin_no": make_field("certificate_of_origin_no", "Certificate of Origin Number"),
        "certificate_of_origin_date": make_field(
            "certificate_of_origin_date",
            "Certificate of Origin Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "invoice_date": make_field("invoice_date", "Invoice Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        # Added to align with docs_json_2
        "HS_code": make_field("HS_code", "HS Code"),
        "producer": make_field("producer", "Producer"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "exporter": make_field("exporter", "Exporter"),
        "destination": make_field("destination", "Destination"),
        "container_no": make_field("container_no", "Container Number"),
        "vessel": make_field("vessel", "Vessel"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "importer": make_field("importer", "Importer"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "price_per_unit": make_field("price_per_unit", "Price per Unit"),
                "total_price": make_field("total_price", "Total Price"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
            }
        ),
    },
)


VETERINARY_CERTIFICATE_SCHEMA = DocumentSchema(
    doc_type=DocumentType.VETERINARY_CERTIFICATE,
    fields={
        "veterinary_certificate_no": make_field("veterinary_certificate_no", "Veterinary Certificate Number"),
        "veterinary_certificate_date": make_field(
            "veterinary_certificate_date",
            "Veterinary Certificate Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "producer": make_field("producer", "Producer"),
        "buyer": make_field("buyer", "Buyer"),
        "exporter": make_field("exporter", "Exporter"),
        "vessel": make_field("vessel", "Vessel"),
        "container_no": make_field("container_no", "Container Number"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "packages": make_field("packages", "Packages"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "factory_number": make_field("factory_number", "Factory Number"),
                "date_of_production": make_field("date_of_production", "Date of Production"),
                "seal_number": make_field("seal_number", "Seal Number"),
                "unit_box": make_field("unit_box", "Units per Box"),
            }
        ),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
    },
)


PROFORMA_SCHEMA = DocumentSchema(
    doc_type=DocumentType.PROFORMA,
    fields={
        "proforma_date": make_field("proforma_date", "Proforma Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "proforma_no": make_field("proforma_no", "Proforma Number"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "HS_code": make_field("HS_code", "HS Code"),
        "contract_no": make_field("contract_no", "Contract Number"),
        "additional_agreements": make_field("additional_agreements", "Additional Agreements"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "producer": make_field("producer", "Producer"),
        "incoterms": make_field("incoterms", "Incoterms"),
        "terms_of_payment": make_field("terms_of_payment", "Terms of Payment"),
        "bank_details": make_field("bank_details", "Bank Details"),
        "total_price": make_field("total_price", "Total Price"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
                "price_per_unit": make_field("price_per_unit", "Price per Unit"),
                "total_price": make_field("total_price", "Total Price"),
            }
        ),
    },
)


CMR_SCHEMA = DocumentSchema(
    doc_type=DocumentType.CMR,
    fields={
        "cmr_date": make_field("cmr_date", "CMR Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "exporter": make_field("exporter", "Exporter"),
        "importer": make_field("importer", "Importer"),
        "incoterms": make_field("incoterms", "Incoterms", fmt=r"^[A-Z]{3}$"),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "veterinary_certificate_no": make_field("veterinary_certificate_no", "Veterinary Certificate Number"),
        "destination": make_field("destination", "Destination"),
        "container_no": make_field("container_no", "Container Number"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "products": build_products_field(
            extra_fields={
                "gross_weight_with_pallets": make_field(
                    "gross_weight_with_pallets", "Gross Weight with Pallets"
                ),
            }
        ),
    },
)


SPECIFICATION_SCHEMA = DocumentSchema(
    doc_type=DocumentType.SPECIFICATION,
    fields={
        "specification_date": make_field(
            "specification_date",
            "Specification Date",
            fmt=r"^\\d{4}-\\d{2}-\\d{2}$",
        ),
        "contract_no": make_field("contract_no", "Contract Number"),
        "additional_agreements": make_field("additional_agreements", "Additional Agreements"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "incoterms": make_field("incoterms", "Incoterms"),
        "terms_of_payment": make_field("terms_of_payment", "Terms of Payment"),
        "total_price": make_field("total_price", "Total Price"),
        # Added to align with docs_json_2
        "HS_code": make_field("HS_code", "HS Code"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "packages": make_field("packages", "Packages"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "size_product": make_field("size_product", "Product Size"),
        "unit_box": make_field("unit_box", "Units per Box"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
                "price_per_unit": make_field("price_per_unit", "Price per Unit"),
                "total_price": make_field("total_price", "Total Price"),
            }
        ),
    },
)


FORM_A_SCHEMA = DocumentSchema(
    doc_type=DocumentType.FORM_A,
    fields={
        "form_a_no": make_field("form_a_no", "FORM A Number"),
        "form_a_date": make_field("form_a_date", "FORM A Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "invoice_date": make_field("invoice_date", "Invoice Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "exporter": make_field("exporter", "Exporter"),
        "importer": make_field("importer", "Importer"),
        "destination": make_field("destination", "Destination"),
        "container_no": make_field("container_no", "Container Number"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
                "HS_code": make_field("HS_code", "HS Code"),
            }
        ),
    },
)


EAV_SCHEMA = DocumentSchema(
    doc_type=DocumentType.EAV,
    fields={
        "eav_no": make_field("eav_no", "EAV Number"),
        "eav_date": make_field("eav_date", "EAV Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "invoice_date": make_field("invoice_date", "Invoice Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "exporter": make_field("exporter", "Exporter"),
        "importer": make_field("importer", "Importer"),
        "destination": make_field("destination", "Destination"),
        "container_no": make_field("container_no", "Container Number"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
                "HS_code": make_field("HS_code", "HS Code"),
            }
        ),
    },
)


CT3_SCHEMA = DocumentSchema(
    doc_type=DocumentType.CT_3,
    fields={
        "ct3_no": make_field("ct3_no", "CT-3 Number"),
        "ct3_date": make_field("ct3_date", "CT-3 Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "invoice_date": make_field("invoice_date", "Invoice Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
        "exporter": make_field("exporter", "Exporter"),
        "importer": make_field("importer", "Importer"),
        "destination": make_field("destination", "Destination"),
        "container_no": make_field("container_no", "Container Number"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "products": build_products_template(
            children={
                "name_product": make_field("name_product", "Product Name"),
                "latin_name": make_field("latin_name", "Latin Name"),
                "size_product": make_field("size_product", "Product Size"),
                "unit_box": make_field("unit_box", "Units per Box"),
                "packages": make_field("packages", "Packages"),
                "net_weight": make_field("net_weight", "Net Weight"),
                "gross_weight": make_field("gross_weight", "Gross Weight"),
                "HS_code": make_field("HS_code", "HS Code"),
            }
        ),
    },
)


CONTRACT_SCHEMA = DocumentSchema(
    doc_type=DocumentType.CONTRACT,
    fields={
        "contract_no": make_field("contract_no", "Contract Number"),
        "contract_date": make_field("contract_date", "Contract Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "additional_agreements": make_field("additional_agreements", "Additional Agreements"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "incoterms": make_field("incoterms", "Incoterms"),
        "terms_of_payment": make_field("terms_of_payment", "Terms of Payment"),
        "bank_details": make_field("bank_details", "Bank Details"),
        "total_price": make_field("total_price", "Total Price"),
    },
)


DOCUMENT_SCHEMAS: Dict[DocumentType, DocumentSchema] = {
    schema.doc_type: schema
    for schema in (
        EXPORT_DECLARATION_SCHEMA,
        INVOICE_SCHEMA,
        PACKING_LIST_SCHEMA,
        BILL_OF_LANDING_SCHEMA,
        PRICE_LIST_1_SCHEMA,
        PRICE_LIST_2_SCHEMA,
        QUALITY_CERTIFICATE_SCHEMA,
        CERTIFICATE_OF_ORIGIN_SCHEMA,
        VETERINARY_CERTIFICATE_SCHEMA,
        PROFORMA_SCHEMA,
        SPECIFICATION_SCHEMA,
        CMR_SCHEMA,
        FORM_A_SCHEMA,
        EAV_SCHEMA,
        CT3_SCHEMA,
        CONTRACT_SCHEMA,
    )
}


def get_schema(doc_type: DocumentType) -> DocumentSchema:
    if doc_type in DOCUMENT_SCHEMAS:
        return DOCUMENT_SCHEMAS[doc_type]
    return DocumentSchema(doc_type=doc_type, fields={})
