import { describe, expect, it } from "vitest";
import { autoMapMongoProduct } from "../src/mongo.js";


describe("autoMapMongoProduct", () => {
  it("maps common Node and Mongo commerce fields without configuration", () => {
    const product = autoMapMongoProduct({
      _id: "product-1",
      name: "Oak Dining Table",
      description: "Solid oak table",
      slug: "oak-dining-table",
      vendor: "Northstar",
      categories: [{ name: "Dining" }],
      specifications: {
        material: "Oak",
        dimensions: { width: 180, unit: "cm" },
        customerToken: "must-not-leave-the-project",
      },
      images: [{ src: "https://cdn.example.com/table.jpg", alt: "Oak table" }],
      variants: [
        {
          _id: "variant-1",
          sku: "TABLE-OAK-180",
          price: 1299,
          optionValues: { Size: "180 cm" },
        },
      ],
      updatedAt: new Date("2026-07-28T10:00:00Z"),
    });

    expect(product).toMatchObject({
      id: "product-1",
      title: "Oak Dining Table",
      brand: "Northstar",
      categories: ["Dining"],
      variants: [
        {
          id: "variant-1",
          sku: "TABLE-OAK-180",
          price: "1299",
          options: { Size: "180 cm" },
        },
      ],
    });
    expect(product.attributes).toEqual({
      material: "Oak",
      dimensions: { width: 180, unit: "cm" },
    });
    expect(JSON.stringify(product)).not.toContain("must-not-leave-the-project");
  });

  it("supports explicit selectors for unusual project schemas", () => {
    const product = autoMapMongoProduct(
      {
        key: "custom-1",
        copy: { heading: "Custom chair", body: "Description" },
      },
      {
        id: "key",
        title: "copy.heading",
        description: (document) => document.copy.body,
      },
    );

    expect(product.id).toBe("custom-1");
    expect(product.title).toBe("Custom chair");
    expect(product.description).toBe("Description");
  });

  it("fails closed when identity or title cannot be inferred", () => {
    expect(() => autoMapMongoProduct({ description: "No identity" })).toThrow();
  });
});
