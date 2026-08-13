import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { MediaCountryNode } from "./mediaContracts";
import { formatCountryName } from "./mediaPresentation";

export interface MediaGlobeProps {
  readonly nodes: readonly MediaCountryNode[];
  readonly selectedCountry: string | null;
  readonly onSelect: (countryCode: string | null) => void;
}

interface MarkerHandle {
  readonly node: MediaCountryNode;
  readonly point: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
  readonly pointMaterial: THREE.MeshBasicMaterial;
  readonly ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  readonly ringMaterial: THREE.MeshBasicMaterial;
  readonly baseScale: number;
}

const globeRadius = 1;
const markerRadius = 1.026;
const idleRotationSpeed = 0.045;
const earthTextureUrl = "/earth/day.webp";
const idlePitch = THREE.MathUtils.degToRad(-10);

const globeVertexShader = `
  varying vec3 vObjectPosition;
  varying vec3 vViewNormal;
  varying vec2 vUv;

  void main() {
    vObjectPosition = normalize(position);
    vViewNormal = normalize(normalMatrix * normal);
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const globeFragmentShader = `
  varying vec3 vObjectPosition;
  varying vec3 vViewNormal;
  varying vec2 vUv;
  uniform float uTime;
  uniform sampler2D uEarthMap;
  uniform float uEarthReady;

  void main() {
    float light = 0.30 + 0.70 * max(
      dot(normalize(vViewNormal), normalize(vec3(-0.34, 0.48, 0.84))),
      0.0
    );
    vec3 deep = vec3(0.010, 0.027, 0.044);
    vec3 lit = vec3(0.035, 0.105, 0.135);
    vec3 color = mix(deep, lit, light);

    if (uEarthReady > 0.5) {
      // SphereGeometry places lon=0 on +X, while media markers place lon=0 on +Z.
      // Advancing U by a quarter turn keeps the geographic surface and API nodes aligned.
      vec2 earthUv = vec2(fract(vUv.x + 0.25), vUv.y);
      vec3 earthTexel = texture2D(uEarthMap, earthUv).rgb;
      float oceanByRed = smoothstep(0.045, 0.078, earthTexel.b - earthTexel.r);
      float oceanByGreen = smoothstep(0.020, 0.052, earthTexel.b - earthTexel.g);
      float landMask = 1.0 - oceanByRed * oceanByGreen;
      float surfaceDetail = dot(earthTexel, vec3(0.299, 0.587, 0.114));
      vec3 landDeep = vec3(0.052, 0.150, 0.165);
      vec3 landLit = vec3(0.180, 0.405, 0.420);
      vec3 landColor = mix(
        landDeep,
        landLit,
        smoothstep(0.08, 0.88, surfaceDetail)
      );
      float coast = 1.0 - smoothstep(0.08, 0.24, abs(landMask - 0.5));
      color = mix(color, landColor * (0.72 + light * 0.46), landMask * 0.92);
      color += vec3(0.22, 0.58, 0.60) * coast * 0.18;
    }

    float minorLat = abs(fract(vUv.y * 18.0) - 0.5);
    float minorLon = abs(fract(vUv.x * 36.0) - 0.5);
    float majorLat = abs(fract(vUv.y * 6.0) - 0.5);
    float majorLon = abs(fract(vUv.x * 12.0) - 0.5);
    float minorGrid = max(
      smoothstep(0.034, 0.0, minorLat),
      smoothstep(0.022, 0.0, minorLon)
    );
    float majorGrid = max(
      smoothstep(0.020, 0.0, majorLat),
      smoothstep(0.012, 0.0, majorLon)
    );
    float scan = smoothstep(
      0.045,
      0.0,
      abs(fract(vUv.y * 0.5 + uTime * 0.018) - 0.5)
    );
    color += vec3(0.16, 0.48, 0.58) * minorGrid * 0.10;
    color += vec3(0.22, 0.66, 0.72) * majorGrid * 0.16;
    color += vec3(0.18, 0.58, 0.64) * scan * 0.06;

    float edge = pow(1.0 - max(dot(normalize(vViewNormal), vec3(0.0, 0.0, 1.0)), 0.0), 2.6);
    color += vec3(0.16, 0.48, 0.58) * edge * 0.22;
    gl_FragColor = vec4(color, 1.0);
  }
`;

function latLonToVector(lat: number, lon: number, radius: number): THREE.Vector3 {
  const latitudeRadians = THREE.MathUtils.degToRad(lat);
  const longitudeRadians = THREE.MathUtils.degToRad(lon);
  const latitudeRadius = Math.cos(latitudeRadians) * radius;

  return new THREE.Vector3(
    latitudeRadius * Math.sin(longitudeRadians),
    Math.sin(latitudeRadians) * radius,
    latitudeRadius * Math.cos(longitudeRadians),
  );
}

function markerScale(articleCount: number, maximumArticleCount: number): number {
  if (maximumArticleCount === 0) {
    return 0.78;
  }

  return 0.78 + Math.sqrt(articleCount / maximumArticleCount) * 0.92;
}

function createSensorLattice(pointCount: number): THREE.BufferGeometry {
  const positions = new Float32Array(pointCount * 3);
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  for (let index = 0; index < pointCount; index += 1) {
    const y = 1 - (index / (pointCount - 1)) * 2;
    const horizontalRadius = Math.sqrt(1 - y * y);
    const longitude = goldenAngle * index;
    positions[index * 3] = horizontalRadius * Math.cos(longitude) * 1.006;
    positions[index * 3 + 1] = y * 1.006;
    positions[index * 3 + 2] = horizontalRadius * Math.sin(longitude) * 1.006;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

  return geometry;
}

function disposeObjectTree(root: THREE.Object3D): void {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();

  root.traverse((object) => {
    if (
      !(object instanceof THREE.Mesh) &&
      !(object instanceof THREE.Points) &&
      !(object instanceof THREE.Line)
    ) {
      return;
    }

    geometries.add(object.geometry);
    const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
    objectMaterials.forEach((material) => materials.add(material));
  });

  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
}

function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState<boolean>(() =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updatePreference = (): void => {
      setPrefersReducedMotion(mediaQuery.matches);
    };

    mediaQuery.addEventListener("change", updatePreference);

    return () => {
      mediaQuery.removeEventListener("change", updatePreference);
    };
  }, []);

  return prefersReducedMotion;
}

/**
 * The sphere shader, atmosphere shell, marker projection, and teardown pattern are
 * adapted from MatrAIx DigitalGlobe. A NASA Blue Marble derivative supplies geographic
 * context only; random particles, cities, and decorative links are intentionally
 * excluded, and all visible media hotspots come from props.
 */
export function MediaGlobe({
  nodes,
  selectedCountry,
  onSelect,
}: MediaGlobeProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const markerHandlesRef = useRef<Map<string, MarkerHandle>>(new Map());
  const onSelectRef = useRef<(countryCode: string | null) => void>(onSelect);
  const selectedCountryRef = useRef<string | null>(selectedCountry);
  const targetRotationRef = useRef<number | null>(null);
  const targetPitchRef = useRef<number>(idlePitch);
  const focusCountryRef = useRef<(countryCode: string | null) => void>(() => undefined);
  const [renderError, setRenderError] = useState<Error | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const sortedNodes = useMemo(
    () => [...nodes].sort((left, right) => right.article_count - left.article_count),
    [nodes],
  );

  onSelectRef.current = onSelect;
  selectedCountryRef.current = selectedCountry;

  useEffect(() => {
    const container = containerRef.current;

    if (container === null) {
      throw new Error("MediaGlobe cannot mount because its container is missing.");
    }

    setRenderError(null);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    camera.position.set(0, 0.04, 3.42);
    camera.lookAt(0, 0, 0);

    let renderer: THREE.WebGLRenderer;

    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
    } catch (error: unknown) {
      const reason = error instanceof Error ? error.message : "unknown WebGL initialization error";
      setRenderError(
        new Error(`无法启动 3D 媒体地球。请确认浏览器已启用 WebGL。reason=${reason}`),
      );
      return undefined;
    }

    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.className = "media-globe-canvas";
    renderer.domElement.setAttribute("aria-hidden", "true");
    container.appendChild(renderer.domElement);
    let disposed = false;

    const tiltGroup = new THREE.Group();
    tiltGroup.rotation.z = THREE.MathUtils.degToRad(-6);
    const pitchGroup = new THREE.Group();
    pitchGroup.rotation.x = idlePitch;
    const globeGroup = new THREE.Group();
    globeGroup.rotation.y = THREE.MathUtils.degToRad(-18);
    scene.add(tiltGroup);
    tiltGroup.add(pitchGroup);
    pitchGroup.add(globeGroup);

    const globeUniforms: {
      readonly uTime: { value: number };
      readonly uEarthMap: { value: THREE.Texture | null };
      readonly uEarthReady: { value: number };
    } = {
      uTime: { value: 0 },
      uEarthMap: { value: null },
      uEarthReady: { value: 0 },
    };
    const globe = new THREE.Mesh(
      new THREE.SphereGeometry(globeRadius, 96, 64),
      new THREE.ShaderMaterial({
        uniforms: globeUniforms,
        vertexShader: globeVertexShader,
        fragmentShader: globeFragmentShader,
      }),
    );
    globeGroup.add(globe);

    const earthTexture = new THREE.TextureLoader().load(
      earthTextureUrl,
      (loadedTexture) => {
        if (disposed) {
          loadedTexture.dispose();
          return;
        }

        globeUniforms.uEarthMap.value = loadedTexture;
        globeUniforms.uEarthReady.value = 1;
        renderer.render(scene, camera);
      },
      undefined,
      () => {
        if (disposed) {
          return;
        }

        setRenderError(
          new Error(
            `无法加载地球大陆底图 ${earthTextureUrl}。请确认前端静态资源已完整部署后重试。`,
          ),
        );
      },
    );
    earthTexture.wrapS = THREE.RepeatWrapping;
    earthTexture.colorSpace = THREE.NoColorSpace;
    earthTexture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());

    const sensorLattice = new THREE.Points(
      createSensorLattice(4_800),
      new THREE.PointsMaterial({
        color: 0x4ca6b5,
        transparent: true,
        opacity: 0.13,
        size: 0.0052,
        sizeAttenuation: true,
        depthWrite: false,
      }),
    );
    globeGroup.add(sensorLattice);

    const atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(globeRadius * 1.075, 72, 48),
      new THREE.ShaderMaterial({
        side: THREE.BackSide,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        uniforms: { uColor: { value: new THREE.Color(0x62d6df) } },
        vertexShader: `
          varying vec3 vViewNormal;
          void main() {
            vViewNormal = normalize(normalMatrix * normal);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: `
          uniform vec3 uColor;
          varying vec3 vViewNormal;
          void main() {
            float intensity = pow(
              max(0.0, 0.66 - dot(normalize(vViewNormal), vec3(0.0, 0.0, 1.0))),
              2.8
            );
            gl_FragColor = vec4(uColor, intensity * 0.34);
          }
        `,
      }),
    );
    globeGroup.add(atmosphere);

    const maximumArticleCount = nodes.reduce(
      (maximum, node) => Math.max(maximum, node.article_count),
      0,
    );
    const pointGeometry = new THREE.SphereGeometry(0.017, 14, 10);
    const ringGeometry = new THREE.RingGeometry(0.029, 0.043, 32);
    const markerMeshes: THREE.Object3D[] = [];
    const markerHandles = new Map<string, MarkerHandle>();

    nodes.forEach((node) => {
      const direction = latLonToVector(node.lat, node.lon, 1).normalize();
      const pointMaterial = new THREE.MeshBasicMaterial({ color: 0x7ce8ee });
      const point = new THREE.Mesh(pointGeometry, pointMaterial);
      const ringMaterial = new THREE.MeshBasicMaterial({
        color: 0x5fc8d2,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.44,
      });
      const ring = new THREE.Mesh(ringGeometry, ringMaterial);
      const marker = new THREE.Group();
      const baseScale = markerScale(node.article_count, maximumArticleCount);
      const orientation = new THREE.Quaternion().setFromUnitVectors(
        new THREE.Vector3(0, 0, 1),
        direction,
      );

      point.scale.setScalar(baseScale);
      point.userData.countryCode = node.country_code;
      ring.userData.countryCode = node.country_code;
      ring.scale.setScalar(baseScale);
      marker.position.copy(direction.multiplyScalar(markerRadius));
      marker.quaternion.copy(orientation);
      marker.add(ring, point);
      globeGroup.add(marker);
      markerMeshes.push(point, ring);
      markerHandles.set(node.country_code, {
        node,
        point,
        pointMaterial,
        ring,
        ringMaterial,
        baseScale,
      });
    });

    markerHandlesRef.current = markerHandles;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    const countryAtPointer = (event: PointerEvent): string | null => {
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
      pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const intersection = raycaster.intersectObjects([globe, ...markerMeshes], false)[0];

      if (intersection?.object === globe) {
        return null;
      }

      const countryCode = intersection?.object.userData.countryCode;

      return typeof countryCode === "string" ? countryCode : null;
    };

    const selectPointerCountry = (event: PointerEvent): void => {
      const countryCode = countryAtPointer(event);

      if (countryCode !== null) {
        onSelectRef.current(countryCode);
      }
    };

    const updatePointerCursor = (event: PointerEvent): void => {
      renderer.domElement.style.cursor = countryAtPointer(event) === null ? "default" : "pointer";
    };

    const clearPointerCursor = (): void => {
      renderer.domElement.style.cursor = "default";
    };

    renderer.domElement.addEventListener("click", selectPointerCountry);
    renderer.domElement.addEventListener("pointermove", updatePointerCursor);
    renderer.domElement.addEventListener("pointerleave", clearPointerCursor);

    const resize = (): void => {
      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);
      const isMobileOrNarrow = window.matchMedia(
        "(max-width: 900px), (pointer: coarse)",
      ).matches;
      renderer.setPixelRatio(
        Math.min(window.devicePixelRatio, isMobileOrNarrow ? 1.5 : 2),
      );
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      renderer.render(scene, camera);
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    resize();

    let animationFrame = 0;
    let previousFrameTime = performance.now();
    let documentIsVisible = !document.hidden;
    const initialBounds = renderer.domElement.getBoundingClientRect();
    let canvasIsVisible =
      initialBounds.bottom > 0 &&
      initialBounds.right > 0 &&
      initialBounds.top < window.innerHeight &&
      initialBounds.left < window.innerWidth;

    const renderScene = (): void => {
      if (!disposed) {
        renderer.render(scene, camera);
      }
    };
    const focusCountry = (countryCode: string | null): void => {
      const node = countryCode === null ? undefined : markerHandles.get(countryCode)?.node;
      const targetRotation =
        node === undefined ? null : -THREE.MathUtils.degToRad(node.lon);
      const targetPitch = node === undefined ? idlePitch : THREE.MathUtils.degToRad(node.lat);
      targetRotationRef.current = targetRotation;
      targetPitchRef.current = targetPitch;

      if (prefersReducedMotion && targetRotation !== null) {
        globeGroup.rotation.y = targetRotation;
      }

      if (prefersReducedMotion) {
        pitchGroup.rotation.x = targetPitch;
      }

      renderScene();
    };
    focusCountryRef.current = focusCountry;
    focusCountry(selectedCountryRef.current);

    const animate = (frameTime: number): void => {
      animationFrame = 0;

      if (disposed || !documentIsVisible || !canvasIsVisible) {
        return;
      }

      const elapsedSeconds = Math.min((frameTime - previousFrameTime) / 1_000, 0.1);
      previousFrameTime = frameTime;
      globeUniforms.uTime.value = frameTime / 1_000;
      const targetRotation = targetRotationRef.current;

      if (targetRotation === null) {
        globeGroup.rotation.y += idleRotationSpeed * elapsedSeconds;
      } else {
        const rotationDelta = Math.atan2(
          Math.sin(targetRotation - globeGroup.rotation.y),
          Math.cos(targetRotation - globeGroup.rotation.y),
        );
        globeGroup.rotation.y += rotationDelta * Math.min(1, elapsedSeconds * 4.5);
      }

      pitchGroup.rotation.x +=
        (targetPitchRef.current - pitchGroup.rotation.x) *
        Math.min(1, elapsedSeconds * 4.5);

      renderScene();
      animationFrame = window.requestAnimationFrame(animate);
    };

    const stopAnimation = (): void => {
      if (animationFrame !== 0) {
        window.cancelAnimationFrame(animationFrame);
        animationFrame = 0;
      }
    };

    const updateAnimationState = (): void => {
      const shouldAnimate =
        !disposed && !prefersReducedMotion && documentIsVisible && canvasIsVisible;

      if (!shouldAnimate) {
        stopAnimation();
        return;
      }

      if (animationFrame === 0) {
        previousFrameTime = performance.now();
        animationFrame = window.requestAnimationFrame(animate);
      }
    };

    const handleVisibilityChange = (): void => {
      documentIsVisible = !document.hidden;
      updateAnimationState();
    };
    const intersectionObserver = new IntersectionObserver((entries) => {
      const canvasEntry = entries.find((entry) => entry.target === renderer.domElement);

      if (canvasEntry === undefined) {
        return;
      }

      canvasIsVisible = canvasEntry.isIntersecting && canvasEntry.intersectionRatio > 0;
      updateAnimationState();
    });

    document.addEventListener("visibilitychange", handleVisibilityChange);
    intersectionObserver.observe(renderer.domElement);

    if (prefersReducedMotion) {
      renderScene();
    } else {
      updateAnimationState();
    }

    return () => {
      disposed = true;
      stopAnimation();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      intersectionObserver.disconnect();
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener("click", selectPointerCountry);
      renderer.domElement.removeEventListener("pointermove", updatePointerCursor);
      renderer.domElement.removeEventListener("pointerleave", clearPointerCursor);
      focusCountryRef.current = () => undefined;
      markerHandlesRef.current = new Map();
      disposeObjectTree(scene);
      earthTexture.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [nodes, prefersReducedMotion]);

  useEffect(() => {
    const markerHandles = markerHandlesRef.current;

    markerHandles.forEach((handle, countryCode) => {
      const isSelected = countryCode === selectedCountry;
      const scale = handle.baseScale * (isSelected ? 1.34 : 1);
      handle.point.scale.setScalar(scale);
      handle.ring.scale.setScalar(scale);
      handle.pointMaterial.color.setHex(isSelected ? 0xffc98a : 0x7ce8ee);
      handle.ringMaterial.color.setHex(isSelected ? 0xffa95c : 0x5fc8d2);
      handle.ringMaterial.opacity = isSelected ? 0.9 : 0.48;
    });

    focusCountryRef.current(selectedCountry);
  }, [selectedCountry, nodes]);

  return (
    <div className="media-globe">
      <div
        ref={containerRef}
        className="media-globe-stage"
        role="img"
        aria-label={`全球媒体热点，共 ${nodes.length} 个国家节点。大陆底图用于地理定位，节点大小表示报道数量。`}
      >
        {renderError === null ? null : (
          <div className="media-globe-error" role="alert">
            <strong>3D 地球不可用</strong>
            <p>{renderError.message}</p>
          </div>
        )}
      </div>

      <label className="globe-country-control">
        <span>定位国家热点</span>
        <select
          value={selectedCountry ?? ""}
          disabled={sortedNodes.length === 0}
          onChange={(event) => {
            onSelect(event.target.value === "" ? null : event.target.value);
          }}
        >
          <option value="">{sortedNodes.length === 0 ? "暂无热点" : "自动巡航"}</option>
          {sortedNodes.map((node) => (
            <option key={node.country_code} value={node.country_code}>
              {formatCountryName(node.country_code)} · {node.article_count.toLocaleString("zh-CN")} 篇
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
