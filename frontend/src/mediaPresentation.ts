const countryNames = new Intl.DisplayNames(["zh-CN"], { type: "region" });
const mediaDateFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatCountryName(countryCode: string): string {
  return countryNames.of(countryCode) ?? countryCode;
}

export function formatMediaTimestamp(timestamp: string): string {
  return mediaDateFormatter.format(new Date(timestamp));
}

export function formatMediaCount(count: number): string {
  return count.toLocaleString("zh-CN");
}
