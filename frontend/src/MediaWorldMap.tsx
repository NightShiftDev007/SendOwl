import { EffectScatterChart, LinesChart, MapChart } from "echarts/charts";
import { GeoComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { init, use, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import type { MediaCountryNode, MediaPropagationEvent } from "./mediaContracts";
import { formatCountryName, formatMediaCount } from "./mediaPresentation";
import { mapNameOf, registerWorldMap, WORLD_MAP_NAME } from "./worldMap";
import "./mediaWorldMap.css";

use([
  MapChart,
  LinesChart,
  EffectScatterChart,
  GeoComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

export interface MediaWorldMapProps {
  readonly nodes: readonly MediaCountryNode[];
  readonly mode: "heat" | "propagation";
  readonly propagationEvents: readonly MediaPropagationEvent[];
  readonly selectedCountry: string | null;
  readonly onSelect: (countryCode: string | null) => void;
}

interface MapDatum {
  readonly name: string;
  readonly value: number;
  readonly countryCode: string;
  readonly topic: string;
}

export function buildMediaMapData(nodes: readonly MediaCountryNode[]): readonly MapDatum[] {
  return nodes.flatMap((node) => {
    const name = mapNameOf(node.country_code);
    return name === null
      ? []
      : [{
          name,
          value: node.article_count,
          countryCode: node.country_code,
          topic: node.topic,
        }];
  });
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function MediaWorldMap({
  nodes,
  mode,
  propagationEvents,
  selectedCountry,
  onSelect,
}: MediaWorldMapProps): JSX.Element {
  const chartElement = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<EChartsType | null>(null);
  const data = useMemo(() => buildMediaMapData(nodes), [nodes]);
  const countryCodeByMapName = useMemo(
    () => new Map(data.map((item) => [item.name, item.countryCode])),
    [data],
  );
  const datumByMapName = useMemo(
    () => new Map(data.map((item) => [item.name, item])),
    [data],
  );
  const nodeByCountry = useMemo(
    () => new Map(nodes.map((node) => [node.country_code, node])),
    [nodes],
  );

  useEffect(() => {
    const element = chartElement.current;
    if (element === null) {
      throw new Error("MediaWorldMap requires a mounted chart container.");
    }

    registerWorldMap();
    const chart = init(element, undefined, { renderer: "canvas" });
    chartInstance.current = chart;
    const handleClick = (event: { readonly name?: string }): void => {
      if (event.name === undefined) {
        return;
      }
      onSelect(countryCodeByMapName.get(event.name) ?? null);
    };
    chart.on("click", handleClick);

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(element);

    return () => {
      resizeObserver.disconnect();
      chart.off("click", handleClick);
      chart.dispose();
      chartInstance.current = null;
    };
  }, [countryCodeByMapName, onSelect]);

  useEffect(() => {
    const chart = chartInstance.current;
    if (chart === null) {
      return;
    }

    const maximumCount = Math.max(1, ...data.map((item) => item.value));
    const propagationLines = propagationEvents.flatMap((event) =>
      event.edges.flatMap((edge) => {
        const origin = nodeByCountry.get(edge.from_country_code);
        const destination = nodeByCountry.get(edge.to_country_code);
        return origin === undefined || destination === undefined
          ? []
          : [{
              coords: [[origin.lon, origin.lat], [destination.lon, destination.lat]],
              topic: event.topic,
              status: event.status,
              lagHours: edge.lag_hours,
              fromCountry: edge.from_country_code,
              toCountry: edge.to_country_code,
              lineStyle: {
                color: event.status === "confirmed" ? "#65d1a7" : "#d99a58",
              },
            }];
      }),
    );
    const propagationPoints = Array.from(
      new Set(propagationLines.flatMap((line) => [line.fromCountry, line.toCountry])),
    ).flatMap((countryCode) => {
      const node = nodeByCountry.get(countryCode);
      return node === undefined
        ? []
        : [{ name: formatCountryName(countryCode), value: [node.lon, node.lat, node.article_count] }];
    });
    const baseOption = {
        animation: !prefersReducedMotion(),
        backgroundColor: "transparent",
        tooltip: {
          trigger: "item",
          renderMode: "richText",
          borderWidth: 0,
          backgroundColor: "#10212b",
          textStyle: { color: "#e8f5f7", fontSize: 12 },
          formatter: (parameters: {
            readonly name: string;
            readonly seriesType?: string;
            readonly data?: {
              readonly topic?: string;
              readonly lagHours?: number;
              readonly fromCountry?: string;
              readonly toCountry?: string;
            };
          }) => {
            if (parameters.seriesType === "lines" && parameters.data !== undefined) {
              return `${parameters.data.topic ?? "传播事件"}\n${formatCountryName(parameters.data.fromCountry ?? "")} → ${formatCountryName(parameters.data.toCountry ?? "")}\n时滞 ${(parameters.data.lagHours ?? 0).toFixed(1)} 小时`;
            }
            const item = datumByMapName.get(parameters.name);
            if (item === undefined) {
              return `${parameters.name}\n暂无媒体统计`;
            }
            return `${formatCountryName(item.countryCode)}\n${formatMediaCount(item.value)} 篇报道\n${item.topic}`;
          },
        },
        visualMap: mode === "heat" ? {
          show: false,
          min: 0,
          max: maximumCount,
          inRange: { color: ["#132a35", "#176075", "#43b4c7"] },
        } : undefined,
      };
    const heatSeries = [
          {
            type: "map",
            map: WORLD_MAP_NAME,
            roam: true,
            scaleLimit: { min: 1, max: 7 },
            selectedMode: "single",
            data,
            itemStyle: {
              areaColor: "#10232d",
              borderColor: "#4c8294",
              borderWidth: 0.7,
            },
            emphasis: {
              label: { show: false },
              itemStyle: { areaColor: "#4ebfd0", borderColor: "#b7e7ed", borderWidth: 1 },
            },
            select: {
              label: { show: false },
              itemStyle: { areaColor: "#d98b4a", borderColor: "#ffd4a9", borderWidth: 1.2 },
            },
          },
        ];
    const propagationSeries = [
      {
        type: "lines",
        coordinateSystem: "geo",
        data: propagationLines,
        lineStyle: { width: 1.3, opacity: 0.68, curveness: 0.26 },
        effect: {
          show: !prefersReducedMotion(),
          period: 5,
          trailLength: 0.25,
          symbol: "arrow",
          symbolSize: 5,
        },
      },
      {
        type: "effectScatter",
        coordinateSystem: "geo",
        data: propagationPoints,
        symbolSize: 7,
        rippleEffect: { brushType: "stroke", scale: 2.5 },
        itemStyle: { color: "#68c3d3" },
      },
    ];
    chart.setOption(
      {
        ...baseOption,
        geo: mode === "propagation" ? {
          map: WORLD_MAP_NAME,
          roam: true,
          scaleLimit: { min: 1, max: 7 },
          itemStyle: { areaColor: "#10232d", borderColor: "#4c8294", borderWidth: 0.7 },
          emphasis: { itemStyle: { areaColor: "#173846" }, label: { show: false } },
        } : undefined,
        series: mode === "heat" ? heatSeries : propagationSeries,
      } as never,
      true,
    );

    if (selectedCountry !== null) {
      const mapName = mapNameOf(selectedCountry);
      if (mapName !== null) {
        chart.dispatchAction({ type: "select", seriesIndex: 0, name: mapName });
      }
    }
  }, [data, datumByMapName, mode, nodeByCountry, propagationEvents, selectedCountry]);

  const sortedNodes = useMemo(
    () => [...nodes].sort((left, right) => left.country_code.localeCompare(right.country_code)),
    [nodes],
  );

  return (
    <div className="media-world-map">
      <div
        ref={chartElement}
        className="media-world-map__canvas"
        role="img"
        aria-label="二维世界媒体热力图，颜色强度表示各国家或地区报道数量"
      />
      {mode === "propagation" && propagationEvents.length === 0 ? (
        <div className="media-world-map__empty" role="status">
          <strong>暂无已识别传播链</strong>
          <span>当前没有首发—跟随事件，地图不会生成装饰飞线。</span>
        </div>
      ) : null}
      <label className="media-world-map__country-control">
        <span>国家焦点</span>
        <select
          value={selectedCountry ?? ""}
          onChange={(event) => onSelect(event.target.value === "" ? null : event.target.value)}
        >
          <option value="">全部国家</option>
          {sortedNodes.map((node) => (
            <option key={node.country_code} value={node.country_code}>
              {formatCountryName(node.country_code)} · {formatMediaCount(node.article_count)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
