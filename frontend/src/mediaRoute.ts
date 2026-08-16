import { z } from "zod";

const mediaLensSchema = z.enum(["articles", "topic", "sources"]);
const topicIdSchema = z.string().uuid();
const sourceIdSchema = z.string().uuid();
const countrySchema = z
  .string()
  .regex(/^[A-Z]{2}$/u, "country must be an uppercase ISO 3166-1 alpha-2 code");
const allowedParameterNames = new Set(["topic_id", "lens", "country", "source_id"]);

export type MediaLens = z.infer<typeof mediaLensSchema>;

export interface MediaRoute {
  readonly topicId: string | null;
  readonly sourceId: string | null;
  readonly lens: MediaLens;
  readonly country: string | null;
}

export type MediaRouteResult =
  | { readonly status: "resolved"; readonly route: MediaRoute }
  | { readonly status: "invalid"; readonly message: string };

function singleParameter(parameters: URLSearchParams, name: string): string | null {
  const values = parameters.getAll(name);

  if (values.length > 1) {
    throw new Error(`参数“${name}”不能重复。`);
  }

  return values[0] ?? null;
}

function parseOptionalTopicId(value: string | null): string | null {
  if (value === null) {
    return null;
  }

  const result = topicIdSchema.safeParse(value);
  if (!result.success) {
    throw new Error("参数“topic_id”必须是合法 UUID。");
  }

  return result.data;
}

function parseOptionalSourceId(value: string | null): string | null {
  if (value === null) {
    return null;
  }

  const result = sourceIdSchema.safeParse(value);
  if (!result.success) {
    throw new Error("参数“source_id”必须是合法 UUID。");
  }

  return result.data;
}

function parseOptionalCountry(value: string | null): string | null {
  if (value === null) {
    return null;
  }

  const result = countrySchema.safeParse(value);
  if (!result.success) {
    throw new Error("参数“country”必须是大写 ISO 3166-1 alpha-2 代码。");
  }

  return result.data;
}

export function resolveMediaRoute(query: string): MediaRouteResult {
  const parameters = new URLSearchParams(query);

  for (const name of parameters.keys()) {
    if (!allowedParameterNames.has(name)) {
      return {
        status: "invalid",
        message: `媒体证据工作区不支持查询参数“${name}”。`,
      };
    }
  }

  try {
    const lensValue = singleParameter(parameters, "lens");
    const lensResult = mediaLensSchema.safeParse(lensValue ?? "articles");
    if (!lensResult.success) {
      return {
        status: "invalid",
        message: "参数“lens”只能是 articles、topic 或 sources。",
      };
    }

    const sourceId = parseOptionalSourceId(singleParameter(parameters, "source_id"));
    const topicId = parseOptionalTopicId(singleParameter(parameters, "topic_id"));
    const country = parseOptionalCountry(singleParameter(parameters, "country"));

    if (sourceId !== null && lensResult.data !== "sources") {
      return {
        status: "invalid",
        message: "参数“source_id”只能与 lens=sources 一起使用。",
      };
    }
    if (lensResult.data === "sources" && (topicId !== null || country !== null)) {
      return {
        status: "invalid",
        message: "lens=sources 不接受 topic_id 或 country 参数。",
      };
    }

    return {
      status: "resolved",
      route: {
        topicId,
        sourceId,
        lens: lensResult.data,
        country,
      },
    };
  } catch (error: unknown) {
    return {
      status: "invalid",
      message: error instanceof Error ? error.message : "媒体证据查询参数解析失败。",
    };
  }
}

export function createMediaHash(route: MediaRoute): string {
  const validatedRoute = z
    .object({
      topicId: topicIdSchema.nullable(),
      sourceId: sourceIdSchema.nullable(),
      lens: mediaLensSchema,
      country: countrySchema.nullable(),
    })
    .strict()
    .superRefine((route, context) => {
      if (route.sourceId !== null && route.lens !== "sources") {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "sourceId requires the sources lens",
          path: ["sourceId"],
        });
      }
      if (route.lens === "sources" && (route.topicId !== null || route.country !== null)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "sources lens cannot include topicId or country",
          path: ["lens"],
        });
      }
    })
    .parse(route);
  const parameters = new URLSearchParams();

  if (validatedRoute.topicId !== null) {
    parameters.set("topic_id", validatedRoute.topicId);
  }
  if (validatedRoute.lens !== "articles") {
    parameters.set("lens", validatedRoute.lens);
  }
  if (validatedRoute.sourceId !== null) {
    parameters.set("source_id", validatedRoute.sourceId);
  }
  if (validatedRoute.country !== null) {
    parameters.set("country", validatedRoute.country);
  }

  const query = parameters.toString();
  return query === "" ? "#/media" : `#/media?${query}`;
}
