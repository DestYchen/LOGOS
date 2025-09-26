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
        "destination": make_field("destination", "Destination"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "unit_box": make_field("unit_box", "Units per Box"),
        "size_product": make_field("size_product", "Product Size"),
        "packages": make_field("packages", "Packages"),
        "net_weight": make_field("net_weight", "Net Weight"),
        "gross_weight": make_field("gross_weight", "Gross Weight"),
        "producer": make_field("producer", "Producer"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "exporter": make_field("exporter", "Exporter"),
        "container_no": make_field("container_no", "Container Number"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "vessel": make_field("vessel", "Vessel"),
        "incoterms": make_field("incoterms", "Incoterms", fmt=r"^[A-Z]{3}$"),
        "total_price": make_field("total_price", "Total Price"),
        "products": build_products_field(),
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
        "commodity_code": make_field("commodity_code", "Commodity Code"),
        "vessel": make_field("vessel", "Vessel"),
        "total_price": make_field("total_price", "Total Price", required=True),
        "products": build_products_field(),
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
        "contract_no": make_field("contract_no", "Contract Number"),
        "invoice_no": make_field("invoice_no", "Invoice Number"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "producer": make_field("producer", "Producer"),
        "container_no": make_field("container_no", "Container Number"),
        "vessel": make_field("vessel", "Vessel"),
        "packages": make_field("packages", "Packages", required=True),
        "net_weight": make_field("net_weight", "Net Weight", required=True),
        "gross_weight": make_field("gross_weight", "Gross Weight", required=True),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "products": build_products_field(
            extra_fields={
                "net_weight_with_glaze": make_field("net_weight_with_glaze", "Net Weight with Glaze"),
                "net_weight_with_ice": make_field("net_weight_with_ice", "Net Weight with Ice"),
                "net_weight_with_glaze_and_pack": make_field(
                    "net_weight_with_glaze_and_pack",
                    "Net Weight with Glaze and Pack",
                ),
            }
        ),
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
        "seller": make_field("seller", "Seller"),
        "buyer": make_field("buyer", "Buyer"),
        "exporter": make_field("exporter", "Exporter"),
        "destination": make_field("destination", "Destination"),
        "packages": make_field("packages", "Packages"),
        "units": make_field("units", "Units"),
        "net_weight": make_field("net_weight", "Net Weight"),
        "gross_weight": make_field("gross_weight", "Gross Weight"),
        "vessel": make_field("vessel", "Vessel"),
        "container_no": make_field("container_no", "Container Number"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
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
        "products": build_products_field(),
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
        "products": build_products_field(),
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
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "net_weight": make_field("net_weight", "Net Weight"),
        "date_of_production": make_field("date_of_production", "Date of Production"),
        "packages": make_field("packages", "Packages"),
        "size_product": make_field("size_product", "Product Size"),
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
        "producer": make_field("producer", "Producer"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "exporter": make_field("exporter", "Exporter"),
        "destination": make_field("destination", "Destination"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "unit_box": make_field("unit_box", "Units per Box"),
        "packages": make_field("packages", "Packages"),
        "net_weight": make_field("net_weight", "Net Weight"),
        "gross_weight": make_field("gross_weight", "Gross Weight"),
        "container_no": make_field("container_no", "Container Number"),
        "vessel": make_field("vessel", "Vessel"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "linear_seal": make_field("linear_seal", "Linear Seal"),
        "importer": make_field("importer", "Importer"),
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
        "seller": make_field("seller", "Seller"),
        "producer": make_field("producer", "Producer"),
        "buyer": make_field("buyer", "Buyer"),
        "exporter": make_field("exporter", "Exporter"),
        "vessel": make_field("vessel", "Vessel"),
        "container_no": make_field("container_no", "Container Number"),
        "packages": make_field("packages", "Packages"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "unit_box": make_field("unit_box", "Units per Box"),
        "net_weight": make_field("net_weight", "Net Weight"),
        "veterinary_seal": make_field("veterinary_seal", "Veterinary Seal"),
        "country_of_origin": make_field("country_of_origin", "Country of Origin"),
    },
)


PROFORMA_SCHEMA = DocumentSchema(
    doc_type=DocumentType.PROFORMA,
    fields={
        "proforma_date": make_field("proforma_date", "Proforma Date", fmt=r"^\\d{4}-\\d{2}-\\d{2}$"),
        "contract_no": make_field("contract_no", "Contract Number"),
        "additional_agreements": make_field("additional_agreements", "Additional Agreements"),
        "buyer": make_field("buyer", "Buyer"),
        "seller": make_field("seller", "Seller"),
        "producer": make_field("producer", "Producer"),
        "incoterms": make_field("incoterms", "Incoterms"),
        "terms_of_payment": make_field("terms_of_payment", "Terms of Payment"),
        "bank_details": make_field("bank_details", "Bank Details"),
        "total_price": make_field("total_price", "Total Price"),
        "net_weight": make_field("net_weight", "Net Weight"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "size_product": make_field("size_product", "Product Size"),
        "unit_box": make_field("unit_box", "Units per Box"),
        "packages": make_field("packages", "Packages"),
        "commodity_code": make_field("commodity_code", "Commodity Code"),
        "products": build_products_field(),
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
        "packages": make_field("packages", "Packages"),
        "name_product": make_field("name_product", "Product Name"),
        "latin_name": make_field("latin_name", "Latin Name"),
        "size_product": make_field("size_product", "Product Size"),
        "unit_box": make_field("unit_box", "Units per Box"),
        "commodity_code": make_field("commodity_code", "Commodity Code"),
        "products": build_products_field(),
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
    )
}


def get_schema(doc_type: DocumentType) -> DocumentSchema:
    if doc_type in DOCUMENT_SCHEMAS:
        return DOCUMENT_SCHEMAS[doc_type]
    return DocumentSchema(doc_type=doc_type, fields={})
