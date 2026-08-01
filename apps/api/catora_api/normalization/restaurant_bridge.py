from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord
from catora_api.db.models.restaurant import (
    RestaurantBrand,
    RestaurantFactObservation,
    RestaurantIdentityAlias,
    RestaurantLocation,
    RestaurantMenu,
    RestaurantMenuItem,
    RestaurantMenuSection,
    RestaurantModifierGroup,
    RestaurantModifierOption,
    RestaurantOfferOrPromotion,
    RestaurantServiceArea,
)
from catora_api.restaurant.projection import projection_hash, stable_canonical_key
from catora_api.schemas.restaurant_bridge import (
    RestaurantBridgeBrand,
    RestaurantBridgeLocation,
    RestaurantBridgeMenu,
    RestaurantBridgeMenuItem,
    RestaurantBridgeOffer,
    RestaurantBridgeServiceArea,
)


@dataclass(frozen=True, slots=True)
class RestaurantBridgeNormalizationSummary:
    brands_created: int = 0
    brands_updated: int = 0
    locations_created: int = 0
    locations_updated: int = 0
    menus_created: int = 0
    menus_updated: int = 0
    menu_items_created: int = 0
    menu_items_updated: int = 0
    modifiers_created: int = 0
    modifiers_updated: int = 0
    offers_created: int = 0
    offers_updated: int = 0
    facts_created: int = 0
    records_rejected: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "brands_created": self.brands_created,
            "brands_updated": self.brands_updated,
            "locations_created": self.locations_created,
            "locations_updated": self.locations_updated,
            "menus_created": self.menus_created,
            "menus_updated": self.menus_updated,
            "menu_items_created": self.menu_items_created,
            "menu_items_updated": self.menu_items_updated,
            "modifiers_created": self.modifiers_created,
            "modifiers_updated": self.modifiers_updated,
            "offers_created": self.offers_created,
            "offers_updated": self.offers_updated,
            "facts_created": self.facts_created,
            "records_rejected": self.records_rejected,
        }


@dataclass(slots=True)
class _Counters:
    brands_created: int = 0
    brands_updated: int = 0
    locations_created: int = 0
    locations_updated: int = 0
    menus_created: int = 0
    menus_updated: int = 0
    menu_items_created: int = 0
    menu_items_updated: int = 0
    modifiers_created: int = 0
    modifiers_updated: int = 0
    offers_created: int = 0
    offers_updated: int = 0
    facts_created: int = 0
    records_rejected: int = 0

    def summary(self) -> RestaurantBridgeNormalizationSummary:
        return RestaurantBridgeNormalizationSummary(**self.__dict__)


class RestaurantBridgeNormalizationPipeline:
    async def normalize_job(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        job: IngestionJob,
    ) -> RestaurantBridgeNormalizationSummary:
        workspace_id = cast(uuid.UUID, source.workspace_id)
        if workspace_id != job.workspace_id:
            raise ValueError("Source and job belong to different workspaces")
        if source.id != job.catalog_source_id:
            raise ValueError("Job does not belong to source")
        if source.config.get("profile") != "restaurant/v1":
            raise ValueError("Catalog source is not a restaurant bridge profile")
        records = (
            await session.scalars(
                select(SourceRecord)
                .where(
                    SourceRecord.workspace_id == workspace_id,
                    SourceRecord.catalog_source_id == source.id,
                    SourceRecord.last_seen_job_id == job.id,
                    SourceRecord.record_type == "restaurant_brand",
                )
                .order_by(SourceRecord.snapshot_at, SourceRecord.id)
            )
        ).all()
        counters = _Counters()
        active_brand_keys: set[str] = set()
        for record in records:
            try:
                payload = RestaurantBridgeBrand.model_validate(record.payload)
            except ValidationError:
                counters.records_rejected += 1
                continue
            brand_key = stable_canonical_key("restaurant-brand", str(source.id), payload.id)
            active_brand_keys.add(brand_key)
            await self._persist_brand(
                session,
                source=source,
                record=record,
                payload=payload,
                brand_key=brand_key,
                counters=counters,
            )
        await self._retire_missing_brands(
            session,
            source=source,
            active_brand_keys=active_brand_keys,
        )
        await session.commit()
        return counters.summary()

    async def _persist_brand(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        record: SourceRecord,
        payload: RestaurantBridgeBrand,
        brand_key: str,
        counters: _Counters,
    ) -> None:
        brand = await session.scalar(
            select(RestaurantBrand).where(
                RestaurantBrand.workspace_id == source.workspace_id,
                RestaurantBrand.canonical_key == brand_key,
            )
        )
        hash_value = projection_hash(payload)
        status = "retired" if payload.status == "deleted" else payload.status
        if brand is None:
            brand = RestaurantBrand(
                workspace_id=source.workspace_id,
                catalog_source_id=source.id,
                canonical_key=brand_key,
                name=payload.name,
                legal_name=payload.legal_name,
                website_url=str(payload.website_url) if payload.website_url else None,
                status=status,
                projection_hash=hash_value,
                deleted_at=datetime.now(UTC) if status == "retired" else None,
            )
            session.add(brand)
            await session.flush()
            counters.brands_created += 1
        else:
            changed = (
                brand.name != payload.name
                or brand.legal_name != payload.legal_name
                or brand.website_url
                != (str(payload.website_url) if payload.website_url else None)
                or brand.status != status
                or brand.projection_hash != hash_value
            )
            brand.name = payload.name
            brand.legal_name = payload.legal_name
            brand.website_url = str(payload.website_url) if payload.website_url else None
            brand.status = status
            brand.projection_hash = hash_value
            brand.deleted_at = datetime.now(UTC) if status == "retired" else None
            if changed:
                counters.brands_updated += 1
        await self._sync_aliases(
            session,
            workspace_id=cast(uuid.UUID, source.workspace_id),
            entity_type="brand",
            entity_id=brand.id,
            aliases=payload.aliases,
            record=record,
        )
        active_location_keys: set[str] = set()
        location_ids: dict[str, uuid.UUID] = {}
        menu_item_ids: dict[str, uuid.UUID] = {}
        for location_payload in payload.locations:
            location_key = stable_canonical_key(
                "restaurant-location",
                str(source.id),
                payload.id,
                location_payload.id,
            )
            active_location_keys.add(location_key)
            location = await self._persist_location(
                session,
                source=source,
                record=record,
                brand=brand,
                brand_external_id=payload.id,
                payload=location_payload,
                location_key=location_key,
                counters=counters,
                menu_item_ids=menu_item_ids,
            )
            location_ids[location_payload.id] = location.id
        await self._retire_missing_locations(
            session,
            brand_id=brand.id,
            active_location_keys=active_location_keys,
        )
        await self._sync_offers(
            session,
            source=source,
            record=record,
            brand=brand,
            payloads=payload.offers,
            location_ids=location_ids,
            menu_item_ids=menu_item_ids,
            counters=counters,
        )

    async def _persist_location(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        record: SourceRecord,
        brand: RestaurantBrand,
        brand_external_id: str,
        payload: RestaurantBridgeLocation,
        location_key: str,
        counters: _Counters,
        menu_item_ids: dict[str, uuid.UUID],
    ) -> RestaurantLocation:
        location = await session.scalar(
            select(RestaurantLocation).where(
                RestaurantLocation.workspace_id == source.workspace_id,
                RestaurantLocation.canonical_key == location_key,
            )
        )
        status = "retired" if payload.status == "deleted" else payload.status
        hash_value = projection_hash(payload)
        address = payload.address.model_dump(mode="json", by_alias=True, exclude_none=True)
        regular_hours = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in payload.regular_hours
        ]
        special_hours = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in payload.special_hours
        ]
        values = {
            "name": payload.name,
            "phone": payload.phone,
            "website_url": str(payload.website_url) if payload.website_url else None,
            "ordering_url": str(payload.ordering_url) if payload.ordering_url else None,
            "address": address,
            "latitude": payload.geo.latitude if payload.geo else None,
            "longitude": payload.geo.longitude if payload.geo else None,
            "regular_hours": regular_hours,
            "special_hours": special_hours,
            "service_modes": list(payload.service_modes),
            "facilities": list(payload.facilities),
            "cuisine_types": list(payload.cuisine_types),
            "status": status,
            "projection_hash": hash_value,
        }
        if location is None:
            location = RestaurantLocation(
                workspace_id=source.workspace_id,
                brand_id=brand.id,
                catalog_source_id=source.id,
                canonical_key=location_key,
                external_location_id=payload.id,
                **values,
                deleted_at=datetime.now(UTC) if status == "retired" else None,
            )
            session.add(location)
            await session.flush()
            counters.locations_created += 1
        else:
            changed = any(getattr(location, key) != value for key, value in values.items())
            for key, value in values.items():
                setattr(location, key, value)
            location.external_location_id = payload.id
            location.deleted_at = datetime.now(UTC) if status == "retired" else None
            if changed:
                counters.locations_updated += 1
        await self._sync_aliases(
            session,
            workspace_id=cast(uuid.UUID, source.workspace_id),
            entity_type="location",
            entity_id=location.id,
            aliases=payload.aliases,
            record=record,
        )
        await self._sync_service_areas(
            session,
            source=source,
            location=location,
            brand_external_id=brand_external_id,
            location_external_id=payload.id,
            payloads=payload.service_areas,
        )
        active_menu_keys: set[str] = set()
        for menu_payload in payload.menus:
            menu_key = stable_canonical_key(
                "restaurant-menu",
                str(source.id),
                brand_external_id,
                payload.id,
                menu_payload.id,
            )
            active_menu_keys.add(menu_key)
            await self._persist_menu(
                session,
                source=source,
                record=record,
                brand=brand,
                location=location,
                brand_external_id=brand_external_id,
                location_external_id=payload.id,
                payload=menu_payload,
                menu_key=menu_key,
                counters=counters,
                menu_item_ids=menu_item_ids,
            )
        await self._retire_missing_menus(
            session,
            location_id=location.id,
            active_menu_keys=active_menu_keys,
        )
        observed_at = payload.updated_at or record.snapshot_at
        for fact_key, value, value_type in (
            ("phone", payload.phone, "string"),
            ("address", address or None, "object"),
            ("regular_hours", regular_hours or None, "list"),
            ("special_hours", special_hours or None, "list"),
            ("service_modes", list(payload.service_modes) or None, "list"),
            ("facilities", list(payload.facilities) or None, "list"),
        ):
            if value is not None:
                counters.facts_created += await self._ensure_fact(
                    session,
                    source_record_id=record.id,
                    workspace_id=cast(uuid.UUID, source.workspace_id),
                    entity_type="location",
                    entity_id=location.id,
                    fact_key=fact_key,
                    value=value,
                    value_type=value_type,
                    observed_at=observed_at,
                )
        return location

    async def _sync_service_areas(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        location: RestaurantLocation,
        brand_external_id: str,
        location_external_id: str,
        payloads: list[RestaurantBridgeServiceArea],
    ) -> None:
        active_keys: set[str] = set()
        for payload in payloads:
            canonical_key = stable_canonical_key(
                "restaurant-service-area",
                str(source.id),
                brand_external_id,
                location_external_id,
                payload.id,
            )
            active_keys.add(canonical_key)
            area = await session.scalar(
                select(RestaurantServiceArea).where(
                    RestaurantServiceArea.location_id == location.id,
                    RestaurantServiceArea.canonical_key == canonical_key,
                )
            )
            status = "retired" if payload.status == "deleted" else payload.status
            values = {
                "label": payload.label,
                "area_type": payload.area_type,
                "geometry": payload.geometry,
                "ordering_url": str(payload.ordering_url) if payload.ordering_url else None,
                "status": status,
            }
            if area is None:
                session.add(
                    RestaurantServiceArea(
                        workspace_id=source.workspace_id,
                        location_id=location.id,
                        canonical_key=canonical_key,
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(area, key, value)
        existing = (
            await session.scalars(
                select(RestaurantServiceArea).where(
                    RestaurantServiceArea.location_id == location.id,
                    RestaurantServiceArea.status != "retired",
                )
            )
        ).all()
        for area in existing:
            if area.canonical_key not in active_keys:
                area.status = "retired"

    async def _persist_menu(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        record: SourceRecord,
        brand: RestaurantBrand,
        location: RestaurantLocation,
        brand_external_id: str,
        location_external_id: str,
        payload: RestaurantBridgeMenu,
        menu_key: str,
        counters: _Counters,
        menu_item_ids: dict[str, uuid.UUID],
    ) -> None:
        menu = await session.scalar(
            select(RestaurantMenu).where(
                RestaurantMenu.workspace_id == source.workspace_id,
                RestaurantMenu.canonical_key == menu_key,
            )
        )
        status = "retired" if payload.status == "deleted" else payload.status
        hash_value = projection_hash(payload)
        values = {
            "name": payload.name,
            "description": payload.description,
            "currency": payload.currency,
            "status": status,
            "available_from": payload.available_from,
            "available_until": payload.available_until,
            "source_updated_at": payload.updated_at,
            "projection_hash": hash_value,
        }
        if menu is None:
            menu = RestaurantMenu(
                workspace_id=source.workspace_id,
                brand_id=brand.id,
                location_id=location.id,
                catalog_source_id=source.id,
                canonical_key=menu_key,
                **values,
            )
            session.add(menu)
            await session.flush()
            counters.menus_created += 1
        else:
            changed = any(getattr(menu, key) != value for key, value in values.items())
            for key, value in values.items():
                setattr(menu, key, value)
            if changed:
                counters.menus_updated += 1
        active_section_keys: set[str] = set()
        for section_payload in payload.sections:
            section_key = stable_canonical_key(
                "restaurant-menu-section",
                str(source.id),
                brand_external_id,
                location_external_id,
                payload.id,
                section_payload.id,
            )
            active_section_keys.add(section_key)
            section = await session.scalar(
                select(RestaurantMenuSection).where(
                    RestaurantMenuSection.menu_id == menu.id,
                    RestaurantMenuSection.canonical_key == section_key,
                )
            )
            if section is None:
                section = RestaurantMenuSection(
                    workspace_id=source.workspace_id,
                    menu_id=menu.id,
                    canonical_key=section_key,
                    name=section_payload.name,
                    description=section_payload.description,
                    position=section_payload.position,
                )
                session.add(section)
                await session.flush()
            else:
                section.name = section_payload.name
                section.description = section_payload.description
                section.position = section_payload.position
            active_item_keys: set[str] = set()
            for item_payload in section_payload.items:
                item_key = stable_canonical_key(
                    "restaurant-menu-item",
                    str(source.id),
                    brand_external_id,
                    location_external_id,
                    payload.id,
                    section_payload.id,
                    item_payload.id,
                )
                active_item_keys.add(item_key)
                item = await self._persist_menu_item(
                    session,
                    source=source,
                    record=record,
                    section=section,
                    payload=item_payload,
                    item_key=item_key,
                    counters=counters,
                )
                menu_item_ids[item_payload.id] = item.id
            existing_items = (
                await session.scalars(
                    select(RestaurantMenuItem).where(
                        RestaurantMenuItem.section_id == section.id,
                        RestaurantMenuItem.status != "retired",
                    )
                )
            ).all()
            for item in existing_items:
                if item.canonical_key not in active_item_keys:
                    item.status = "retired"
        existing_sections = (
            await session.scalars(
                select(RestaurantMenuSection).where(RestaurantMenuSection.menu_id == menu.id)
            )
        ).all()
        for section in existing_sections:
            if section.canonical_key not in active_section_keys:
                for item in (
                    await session.scalars(
                        select(RestaurantMenuItem).where(
                            RestaurantMenuItem.section_id == section.id
                        )
                    )
                ).all():
                    item.status = "retired"

    async def _persist_menu_item(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        record: SourceRecord,
        section: RestaurantMenuSection,
        payload: RestaurantBridgeMenuItem,
        item_key: str,
        counters: _Counters,
    ) -> RestaurantMenuItem:
        item = await session.scalar(
            select(RestaurantMenuItem).where(
                RestaurantMenuItem.section_id == section.id,
                RestaurantMenuItem.canonical_key == item_key,
            )
        )
        status = "retired" if payload.status == "deleted" else payload.status
        availability = payload.availability if status == "active" else "unavailable"
        hash_value = projection_hash(payload)
        values = {
            "name": payload.name,
            "description": payload.description,
            "price_amount": payload.price,
            "currency": payload.currency,
            "dietary_facts": payload.dietary_facts,
            "allergen_facts": payload.allergen_facts,
            "availability_state": availability,
            "status": status,
            "source_updated_at": payload.updated_at,
            "projection_hash": hash_value,
        }
        if item is None:
            item = RestaurantMenuItem(
                workspace_id=source.workspace_id,
                section_id=section.id,
                canonical_key=item_key,
                **values,
            )
            session.add(item)
            await session.flush()
            counters.menu_items_created += 1
        else:
            changed = any(getattr(item, key) != value for key, value in values.items())
            for key, value in values.items():
                setattr(item, key, value)
            if changed:
                counters.menu_items_updated += 1
        await self._sync_modifiers(
            session,
            source=source,
            menu_item=item,
            payload=payload,
            counters=counters,
        )
        observed_at = payload.updated_at or record.snapshot_at
        fact_values: tuple[tuple[str, object | None, str], ...] = (
            ("price", str(payload.price) if payload.price is not None else None, "decimal"),
            ("currency", payload.currency, "string"),
            ("availability", payload.availability, "string"),
            ("dietary_facts", payload.dietary_facts or None, "object"),
            ("allergen_facts", payload.allergen_facts or None, "object"),
            (
                "media",
                [image.model_dump(mode="json", by_alias=True) for image in payload.images]
                or None,
                "list",
            ),
        )
        for fact_key, value, value_type in fact_values:
            if value is not None:
                counters.facts_created += await self._ensure_fact(
                    session,
                    source_record_id=record.id,
                    workspace_id=cast(uuid.UUID, source.workspace_id),
                    entity_type="menu_item",
                    entity_id=item.id,
                    fact_key=fact_key,
                    value=value,
                    value_type=value_type,
                    observed_at=observed_at,
                )
        return item

    async def _sync_modifiers(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        menu_item: RestaurantMenuItem,
        payload: RestaurantBridgeMenuItem,
        counters: _Counters,
    ) -> None:
        active_group_keys: set[str] = set()
        for group_payload in payload.modifiers:
            group_key = stable_canonical_key(
                "restaurant-modifier-group",
                str(source.id),
                str(menu_item.id),
                group_payload.id,
            )
            active_group_keys.add(group_key)
            group = await session.scalar(
                select(RestaurantModifierGroup).where(
                    RestaurantModifierGroup.menu_item_id == menu_item.id,
                    RestaurantModifierGroup.canonical_key == group_key,
                )
            )
            values = {
                "name": group_payload.name,
                "required": group_payload.required,
                "min_selections": group_payload.min_selections,
                "max_selections": group_payload.max_selections,
                "position": group_payload.position,
            }
            if group is None:
                group = RestaurantModifierGroup(
                    workspace_id=source.workspace_id,
                    menu_item_id=menu_item.id,
                    canonical_key=group_key,
                    **values,
                )
                session.add(group)
                await session.flush()
                counters.modifiers_created += 1
            else:
                changed = any(getattr(group, key) != value for key, value in values.items())
                for key, value in values.items():
                    setattr(group, key, value)
                if changed:
                    counters.modifiers_updated += 1
            active_option_keys: set[str] = set()
            for option_payload in group_payload.options:
                option_key = stable_canonical_key(
                    "restaurant-modifier-option",
                    str(source.id),
                    str(group.id),
                    option_payload.id,
                )
                active_option_keys.add(option_key)
                option = await session.scalar(
                    select(RestaurantModifierOption).where(
                        RestaurantModifierOption.modifier_group_id == group.id,
                        RestaurantModifierOption.canonical_key == option_key,
                    )
                )
                option_values = {
                    "name": option_payload.name,
                    "price_delta": option_payload.price_delta,
                    "currency": option_payload.currency,
                    "availability_state": option_payload.availability,
                    "position": option_payload.position,
                }
                if option is None:
                    session.add(
                        RestaurantModifierOption(
                            workspace_id=source.workspace_id,
                            modifier_group_id=group.id,
                            canonical_key=option_key,
                            **option_values,
                        )
                    )
                    counters.modifiers_created += 1
                else:
                    changed = any(
                        getattr(option, key) != value for key, value in option_values.items()
                    )
                    for key, value in option_values.items():
                        setattr(option, key, value)
                    if changed:
                        counters.modifiers_updated += 1
            existing_options = (
                await session.scalars(
                    select(RestaurantModifierOption).where(
                        RestaurantModifierOption.modifier_group_id == group.id
                    )
                )
            ).all()
            for option in existing_options:
                if option.canonical_key not in active_option_keys:
                    option.availability_state = "unavailable"
        existing_groups = (
            await session.scalars(
                select(RestaurantModifierGroup).where(
                    RestaurantModifierGroup.menu_item_id == menu_item.id
                )
            )
        ).all()
        for group in existing_groups:
            if group.canonical_key not in active_group_keys:
                for option in (
                    await session.scalars(
                        select(RestaurantModifierOption).where(
                            RestaurantModifierOption.modifier_group_id == group.id
                        )
                    )
                ).all():
                    option.availability_state = "unavailable"

    async def _sync_offers(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        record: SourceRecord,
        brand: RestaurantBrand,
        payloads: list[RestaurantBridgeOffer],
        location_ids: dict[str, uuid.UUID],
        menu_item_ids: dict[str, uuid.UUID],
        counters: _Counters,
    ) -> None:
        active_keys: set[str] = set()
        for payload in payloads:
            targets: list[tuple[str, uuid.UUID | None, uuid.UUID | None]] = []
            targets.extend(
                (f"location:{external_id}", location_ids.get(external_id), None)
                for external_id in payload.location_ids
            )
            targets.extend(
                (f"menu-item:{external_id}", None, menu_item_ids.get(external_id))
                for external_id in payload.menu_item_ids
            )
            for target_key, location_id, menu_item_id in targets:
                if location_id is None and menu_item_id is None:
                    continue
                canonical_key = stable_canonical_key(
                    "restaurant-offer",
                    str(source.id),
                    payload.id,
                    target_key,
                )
                active_keys.add(canonical_key)
                offer = await session.scalar(
                    select(RestaurantOfferOrPromotion).where(
                        RestaurantOfferOrPromotion.workspace_id == source.workspace_id,
                        RestaurantOfferOrPromotion.canonical_key == canonical_key,
                    )
                )
                values = {
                    "brand_id": brand.id,
                    "location_id": location_id,
                    "menu_item_id": menu_item_id,
                    "name": payload.name,
                    "description": payload.description,
                    "starts_at": payload.starts_at,
                    "ends_at": payload.ends_at,
                    "status": payload.status,
                    "projection_hash": projection_hash(
                        {"offer": payload.model_dump(mode="json"), "target": target_key}
                    ),
                }
                if offer is None:
                    offer = RestaurantOfferOrPromotion(
                        workspace_id=source.workspace_id,
                        canonical_key=canonical_key,
                        **values,
                    )
                    session.add(offer)
                    await session.flush()
                    counters.offers_created += 1
                else:
                    changed = any(getattr(offer, key) != value for key, value in values.items())
                    for key, value in values.items():
                        setattr(offer, key, value)
                    if changed:
                        counters.offers_updated += 1
                counters.facts_created += await self._ensure_fact(
                    session,
                    source_record_id=record.id,
                    workspace_id=cast(uuid.UUID, source.workspace_id),
                    entity_type="offer",
                    entity_id=offer.id,
                    fact_key="status",
                    value=payload.status,
                    value_type="string",
                    observed_at=payload.updated_at or record.snapshot_at,
                )
        existing = (
            await session.scalars(
                select(RestaurantOfferOrPromotion).where(
                    RestaurantOfferOrPromotion.workspace_id == source.workspace_id,
                    RestaurantOfferOrPromotion.brand_id == brand.id,
                    RestaurantOfferOrPromotion.status.not_in(("expired", "cancelled")),
                )
            )
        ).all()
        for offer in existing:
            if offer.canonical_key not in active_keys:
                offer.status = "expired"

    async def _sync_aliases(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        aliases: list[str],
        record: SourceRecord,
    ) -> None:
        normalized = {
            alias.strip().casefold(): alias.strip()
            for alias in aliases
            if alias.strip()
        }
        existing = (
            await session.scalars(
                select(RestaurantIdentityAlias).where(
                    RestaurantIdentityAlias.workspace_id == workspace_id,
                    RestaurantIdentityAlias.entity_type == entity_type,
                    RestaurantIdentityAlias.entity_id == entity_id,
                )
            )
        ).all()
        existing_by_alias = {item.normalized_alias: item for item in existing}
        for normalized_alias, alias in normalized.items():
            item = existing_by_alias.get(normalized_alias)
            if item is None:
                session.add(
                    RestaurantIdentityAlias(
                        workspace_id=workspace_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        alias=alias,
                        normalized_alias=normalized_alias,
                        source_record_id=record.id,
                        status="active",
                    )
                )
            else:
                item.alias = alias
                item.source_record_id = record.id
                item.status = "active"
        for normalized_alias, item in existing_by_alias.items():
            if normalized_alias not in normalized:
                item.status = "retired"

    async def _ensure_fact(
        self,
        session: AsyncSession,
        *,
        source_record_id: uuid.UUID,
        workspace_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        fact_key: str,
        value: object,
        value_type: str,
        observed_at: datetime,
    ) -> int:
        checksum = projection_hash(
            {
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "fact_key": fact_key,
                "value": value,
                "observed_at": observed_at.isoformat(),
            }
        )
        existing = await session.scalar(
            select(RestaurantFactObservation.id).where(
                RestaurantFactObservation.source_record_id == source_record_id,
                RestaurantFactObservation.entity_type == entity_type,
                RestaurantFactObservation.entity_id == entity_id,
                RestaurantFactObservation.fact_key == fact_key,
                RestaurantFactObservation.checksum == checksum,
            )
        )
        if existing is not None:
            return 0
        session.add(
            RestaurantFactObservation(
                workspace_id=workspace_id,
                source_record_id=source_record_id,
                entity_type=entity_type,
                entity_id=entity_id,
                fact_key=fact_key,
                value=cast(Any, value),
                value_type=value_type,
                fact_state="supported",
                confidence="high",
                observed_at=observed_at,
                checksum=checksum,
            )
        )
        return 1

    async def _retire_missing_brands(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        active_brand_keys: set[str],
    ) -> None:
        existing = (
            await session.scalars(
                select(RestaurantBrand).where(
                    RestaurantBrand.workspace_id == source.workspace_id,
                    RestaurantBrand.catalog_source_id == source.id,
                    RestaurantBrand.status != "retired",
                )
            )
        ).all()
        for brand in existing:
            if brand.canonical_key not in active_brand_keys:
                brand.status = "retired"
                brand.deleted_at = datetime.now(UTC)

    async def _retire_missing_locations(
        self,
        session: AsyncSession,
        *,
        brand_id: uuid.UUID,
        active_location_keys: set[str],
    ) -> None:
        existing = (
            await session.scalars(
                select(RestaurantLocation).where(
                    RestaurantLocation.brand_id == brand_id,
                    RestaurantLocation.status != "retired",
                )
            )
        ).all()
        for location in existing:
            if location.canonical_key not in active_location_keys:
                location.status = "retired"
                location.deleted_at = datetime.now(UTC)

    async def _retire_missing_menus(
        self,
        session: AsyncSession,
        *,
        location_id: uuid.UUID,
        active_menu_keys: set[str],
    ) -> None:
        existing = (
            await session.scalars(
                select(RestaurantMenu).where(
                    RestaurantMenu.location_id == location_id,
                    RestaurantMenu.status != "retired",
                )
            )
        ).all()
        for menu in existing:
            if menu.canonical_key not in active_menu_keys:
                menu.status = "retired"
