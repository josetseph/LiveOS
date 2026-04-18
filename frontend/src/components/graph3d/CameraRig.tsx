"use client";

import { useRef, useEffect } from "react";
import { useThree, useFrame } from "@react-three/fiber";
import * as THREE from "three";

const SPEED     = 120;   // units / sec (WASD flight)
const BOOST     = 5;     // Shift multiplier
const DAMPING   = 0.82;  // per-frame velocity falloff
const PAN_SPEED = 0.8;   // world units per screen pixel (right-drag pan)

interface CameraRigProps {
  onCameraMove?:  (pos: THREE.Vector3) => void;
  startPosition?: [number, number, number];
}

export function CameraRig({ onCameraMove, startPosition = [0, 0, 0] }: CameraRigProps) {
  const { camera, gl } = useThree();

  const vel          = useRef(new THREE.Vector3());
  const euler        = useRef(new THREE.Euler(0, 0, 0, "YXZ"));
  const look         = useRef(new THREE.Vector3());
  const right        = useRef(new THREE.Vector3());
  const UP           = useRef(new THREE.Vector3(0, 1, 0));
  const keys         = useRef(new Set<string>());
  const isLeftDown   = useRef(false);
  const isDrag       = useRef(false);
  const isRightDown  = useRef(false);

  useEffect(() => {
    camera.position.set(...startPosition);
    euler.current.setFromQuaternion(camera.quaternion);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const canvas = gl.domElement;

    const onKeyDown = (e: KeyboardEvent) => keys.current.add(e.code);
    const onKeyUp   = (e: KeyboardEvent) => keys.current.delete(e.code);

    const onMouseDown = (e: MouseEvent) => {
      if (e.button === 0) { isLeftDown.current = true;  isDrag.current = false; }
      if (e.button === 2) { isRightDown.current = true; }
    };

    const onMouseMove = (e: MouseEvent) => {
      const dx = e.movementX, dy = e.movementY;
      if (!dx && !dy) return;

      if (isLeftDown.current) {
        isDrag.current = true;
        euler.current.y -= dx * 0.003;
        euler.current.x  = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, euler.current.x - dy * 0.003));
        camera.quaternion.setFromEuler(euler.current);
      }

      if (isRightDown.current) {
        camera.getWorldDirection(look.current);
        right.current.crossVectors(look.current, UP.current).normalize();
        camera.position.addScaledVector(right.current, -dx * PAN_SPEED);
        camera.position.y += dy * PAN_SPEED;
      }
    };

    const onMouseUp = (e: MouseEvent) => {
      if (e.button === 0) isLeftDown.current  = false;
      if (e.button === 2) isRightDown.current = false;
    };

    const onContextMenu = (e: MouseEvent) => e.preventDefault();

    const onClickCapture = (e: MouseEvent) => {
      if (isDrag.current) { e.stopImmediatePropagation(); isDrag.current = false; }
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      camera.getWorldDirection(look.current);
      vel.current.addScaledVector(look.current, -e.deltaY * 0.6);
    };

    window.addEventListener("keydown",       onKeyDown);
    window.addEventListener("keyup",         onKeyUp);
    canvas.addEventListener("mousedown",     onMouseDown);
    window.addEventListener("mousemove",     onMouseMove);
    window.addEventListener("mouseup",       onMouseUp);
    canvas.addEventListener("contextmenu",   onContextMenu);
    canvas.addEventListener("click",         onClickCapture, true);
    canvas.addEventListener("wheel",         onWheel, { passive: false });

    return () => {
      window.removeEventListener("keydown",     onKeyDown);
      window.removeEventListener("keyup",       onKeyUp);
      canvas.removeEventListener("mousedown",   onMouseDown);
      window.removeEventListener("mousemove",   onMouseMove);
      window.removeEventListener("mouseup",     onMouseUp);
      canvas.removeEventListener("contextmenu", onContextMenu);
      canvas.removeEventListener("click",       onClickCapture, true);
      canvas.removeEventListener("wheel",       onWheel);
    };
  }, [camera, gl]); // eslint-disable-line react-hooks/exhaustive-deps

  useFrame((_, delta) => {
    camera.getWorldDirection(look.current);
    right.current.crossVectors(look.current, UP.current).normalize();

    const boost = keys.current.has("ShiftLeft") || keys.current.has("ShiftRight") ? BOOST : 1;
    const spd   = SPEED * boost;

    let mf = 0, mr = 0;
    if (keys.current.has("KeyW")) mf =  1;
    if (keys.current.has("KeyS")) mf = -1;
    if (keys.current.has("KeyD")) mr =  1;
    if (keys.current.has("KeyA")) mr = -1;

    if (mf !== 0) vel.current.addScaledVector(look.current,  mf * spd * delta * 60);
    if (mr !== 0) vel.current.addScaledVector(right.current, mr * spd * delta * 60);

    vel.current.multiplyScalar(DAMPING);

    if (vel.current.lengthSq() > 0.01) {
      camera.position.addScaledVector(vel.current, delta);
      onCameraMove?.(camera.position);
    }
  });

  return null;
}
