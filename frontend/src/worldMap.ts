import { registerMap } from "echarts/core";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";
import countries110m from "world-atlas/countries-110m.json";

export const WORLD_MAP_NAME = "sandowl-world";

const ISO2_TO_MAP_NAME: Readonly<Record<string, string>> = {
  AE: "United Arab Emirates", AF: "Afghanistan", AL: "Albania", AM: "Armenia",
  AO: "Angola", AR: "Argentina", AT: "Austria", AU: "Australia", AZ: "Azerbaijan",
  BA: "Bosnia and Herz.", BD: "Bangladesh", BE: "Belgium", BF: "Burkina Faso",
  BG: "Bulgaria", BH: "Bahrain", BJ: "Benin", BN: "Brunei", BO: "Bolivia",
  BR: "Brazil", BS: "Bahamas", BT: "Bhutan", BW: "Botswana", BY: "Belarus",
  CA: "Canada", CD: "Dem. Rep. Congo", CF: "Central African Rep.", CG: "Congo",
  CH: "Switzerland", CI: "Côte d'Ivoire", CL: "Chile", CM: "Cameroon", CN: "China",
  CO: "Colombia", CR: "Costa Rica", CU: "Cuba", CV: "Cabo Verde", CY: "Cyprus",
  CZ: "Czechia", DE: "Germany", DJ: "Djibouti", DK: "Denmark", DO: "Dominican Rep.",
  DZ: "Algeria", EC: "Ecuador", EE: "Estonia", EG: "Egypt", ER: "Eritrea",
  ES: "Spain", ET: "Ethiopia", FI: "Finland", FJ: "Fiji", FR: "France", GA: "Gabon",
  GB: "United Kingdom", GE: "Georgia", GH: "Ghana", GN: "Guinea", GQ: "Eq. Guinea",
  GR: "Greece", GT: "Guatemala", GW: "Guinea-Bissau", GY: "Guyana", HT: "Haiti",
  HU: "Hungary", ID: "Indonesia", IE: "Ireland", IL: "Israel", IN: "India",
  IQ: "Iraq", IR: "Iran", IS: "Iceland", IT: "Italy", JM: "Jamaica", JO: "Jordan",
  JP: "Japan", KE: "Kenya", KG: "Kyrgyzstan", KH: "Cambodia", KM: "Comoros",
  KR: "South Korea", KW: "Kuwait", KZ: "Kazakhstan", LA: "Laos", LB: "Lebanon",
  LK: "Sri Lanka", LR: "Liberia", LS: "Lesotho", LT: "Lithuania", LU: "Luxembourg",
  LV: "Latvia", LY: "Libya", MA: "Morocco", MD: "Moldova", ME: "Montenegro",
  MG: "Madagascar", MK: "Macedonia", ML: "Mali", MM: "Myanmar", MR: "Mauritania",
  MT: "Malta", MU: "Mauritius", MV: "Maldives", MW: "Malawi", MX: "Mexico",
  MY: "Malaysia", MZ: "Mozambique", NA: "Namibia", NE: "Niger", NG: "Nigeria",
  NI: "Nicaragua", NL: "Netherlands", NO: "Norway", NP: "Nepal", NZ: "New Zealand",
  OM: "Oman", PA: "Panama", PE: "Peru", PG: "Papua New Guinea", PH: "Philippines",
  PK: "Pakistan", PL: "Poland", PS: "Palestine", PT: "Portugal", PY: "Paraguay",
  QA: "Qatar", RO: "Romania", RS: "Serbia", RU: "Russia", RW: "Rwanda",
  SA: "Saudi Arabia", SB: "Solomon Is.", SD: "Sudan", SE: "Sweden", SG: "Singapore",
  SI: "Slovenia", SK: "Slovakia", SL: "Sierra Leone", SN: "Senegal", SO: "Somalia",
  SR: "Suriname", SS: "S. Sudan", ST: "São Tomé and Principe", SV: "El Salvador",
  SY: "Syria", SZ: "eSwatini", TD: "Chad", TG: "Togo", TH: "Thailand",
  TJ: "Tajikistan", TM: "Turkmenistan", TN: "Tunisia", TR: "Turkey",
  TT: "Trinidad and Tobago", TZ: "Tanzania", UA: "Ukraine", UG: "Uganda",
  US: "United States of America", UY: "Uruguay", UZ: "Uzbekistan", VE: "Venezuela",
  VN: "Vietnam", VU: "Vanuatu", YE: "Yemen", ZA: "South Africa", ZM: "Zambia",
  ZW: "Zimbabwe",
};

interface WorldFeature {
  type: string;
  properties?: { name?: string };
  geometry?: { type: string; coordinates: unknown };
}

interface WorldGeoJson {
  type: "FeatureCollection";
  features: WorldFeature[];
}

let registeredMap: WorldGeoJson | null = null;

export function mapNameOf(countryCode: string): string | null {
  return ISO2_TO_MAP_NAME[countryCode.toUpperCase()] ?? null;
}

function longitudeRange(coordinates: unknown): readonly [number, number] | null {
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;

  const visit = (value: unknown): void => {
    if (!Array.isArray(value)) {
      return;
    }
    if (typeof value[0] === "number" && typeof value[1] === "number") {
      minimum = Math.min(minimum, value[0]);
      maximum = Math.max(maximum, value[0]);
      return;
    }
    value.forEach(visit);
  };

  visit(coordinates);
  return Number.isFinite(minimum) ? [minimum, maximum] : null;
}

function unwrapAntimeridian(coordinates: unknown): unknown {
  if (!Array.isArray(coordinates)) {
    return coordinates;
  }
  if (typeof coordinates[0] === "number" && typeof coordinates[1] === "number") {
    return [coordinates[0] < 0 ? coordinates[0] + 360 : coordinates[0], coordinates[1]];
  }
  return coordinates.map(unwrapAntimeridian);
}

function normalizeAntimeridianGeometry(geoJson: WorldGeoJson): WorldGeoJson {
  geoJson.features = geoJson.features.filter(
    (featureItem) => featureItem.properties?.name !== "Antarctica",
  );

  geoJson.features.forEach((featureItem) => {
    const geometry = featureItem.geometry;
    if (geometry === undefined) {
      return;
    }

    if (geometry.type === "MultiPolygon") {
      const polygons = geometry.coordinates as unknown[];
      geometry.coordinates = polygons.map((polygon) => {
        const range = longitudeRange(polygon);
        return range !== null && range[0] < -170 && range[1] > 170
          ? unwrapAntimeridian(polygon)
          : polygon;
      });
      return;
    }

    if (geometry.type === "Polygon") {
      const range = longitudeRange(geometry.coordinates);
      if (range !== null && range[0] < -170 && range[1] > 170) {
        geometry.coordinates = unwrapAntimeridian(geometry.coordinates);
      }
    }
  });

  return geoJson;
}

export function registerWorldMap(): WorldGeoJson {
  if (registeredMap !== null) {
    return registeredMap;
  }

  const topology = countries110m as unknown as Topology;
  const countries = topology.objects.countries;
  if (countries === undefined) {
    throw new Error("The bundled world atlas does not contain a countries object.");
  }
  const geoJson = feature(
    topology,
    countries,
  ) as unknown as WorldGeoJson;
  normalizeAntimeridianGeometry(geoJson);
  registerMap(WORLD_MAP_NAME, geoJson as never);
  registeredMap = geoJson;
  return geoJson;
}
