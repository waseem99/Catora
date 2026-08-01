from decimal import Decimal

from catora_api.restaurant import (
    Address,
    Menu,
    MenuItem,
    MenuSection,
    RestaurantBrandProjection,
    RestaurantLocationProjection,
    restaurant_json_ld,
)


def test_restaurant_json_ld_uses_external_address_keys() -> None:
    brand = RestaurantBrandProjection(
        canonical_key="brand:test:1234567890abcdef1234",
        name="Test Restaurant",
        locations=(
            RestaurantLocationProjection(
                canonical_key="location:test:1234567890abcdef1234",
                name="Test Restaurant Lahore",
                address=Address(
                    street_address="1 Main Road",
                    address_locality="Lahore",
                    address_country="PK",
                ),
            ),
        ),
    )

    location = restaurant_json_ld(brand)["subOrganization"][0]

    assert location["address"] == {
        "@type": "PostalAddress",
        "streetAddress": "1 Main Road",
        "addressLocality": "Lahore",
        "addressCountry": "PK",
    }
    assert "street_address" not in location["address"]


def test_unknown_availability_is_not_projected_as_out_of_stock() -> None:
    brand = RestaurantBrandProjection(
        canonical_key="brand:test:1234567890abcdef1234",
        name="Test Restaurant",
        locations=(
            RestaurantLocationProjection(
                canonical_key="location:test:1234567890abcdef1234",
                name="Test Restaurant Lahore",
                menus=(
                    Menu(
                        canonical_key="menu:test:1234567890abcdef1234",
                        name="Main Menu",
                        sections=(
                            MenuSection(
                                canonical_key="section:test:1234567890abcdef1234",
                                name="Burgers",
                                items=(
                                    MenuItem(
                                        canonical_key="item:test:1234567890abcdef1234",
                                        name="Burger",
                                        price_amount=Decimal("799.00"),
                                        currency="PKR",
                                        availability_state="unknown",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    item = restaurant_json_ld(brand)["subOrganization"][0]["hasMenu"][0][
        "hasMenuSection"
    ][0]["hasMenuItem"][0]

    assert item["offers"]["price"] == "799.00"
    assert "availability" not in item["offers"]
