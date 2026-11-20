/** Three.js Object3D adapter. This module has no serial, network, or hardware side effects. */
export const REST_POSE = Object.freeze({
  base_deg: 0, shoulder_deg: 0, elbow_deg: 0,
  wrist_pitch_deg: 0, wrist_roll_deg: 0, gripper_opening_mm: 85,
});

export function createArmController(scene) {
  const requireNode = name => {
    const node = scene.getObjectByName(name);
    if (!node) throw new Error(`Falta el nodo del brazo: ${name}`);
    return node;
  };
  const config = [
    ['base_deg', 'joint_base', [0, 0, 1]],
    ['shoulder_deg', 'joint_shoulder', [0, 1, 0]],
    ['elbow_deg', 'joint_elbow', [0, 1, 0]],
    ['wrist_pitch_deg', 'joint_wrist_pitch', [0, 1, 0]],
    ['wrist_roll_deg', 'joint_wrist_roll', [1, 0, 0]],
  ];
  const rotations = config.map(([key, name, axis]) => {
    const node = requireNode(name);
    return {key, node, axis, rest: node.quaternion.clone()};
  });
  const gear = requireNode('base_servo_gear');
  const gearRest = gear.quaternion.clone();
  const pinion = requireNode('gripper_pinion');
  const pinionRest = pinion.quaternion.clone();
  const jawA = requireNode('gripper_jaw_A');
  const jawB = requireNode('gripper_jaw_B');
  const restA = jawA.position.clone();
  const restB = jawB.position.clone();
  let state = {...REST_POSE};

  function rotate(node, rest, axis, radians) {
    const half = radians / 2;
    const sin = Math.sin(half);
    const delta = rest.clone().set(axis[0] * sin, axis[1] * sin, axis[2] * sin, Math.cos(half));
    node.quaternion.copy(rest).multiply(delta);
  }

  function setPose(patch = {}) {
    for (const [key, value] of Object.entries(patch)) {
      if (!(key in REST_POSE)) throw new Error(`Control desconocido: ${key}`);
      if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${key} debe ser un número finito`);
    }
    state = {...state, ...patch};
    state.gripper_opening_mm = Math.min(85, Math.max(45, state.gripper_opening_mm));
    for (const {key, node, axis, rest} of rotations) rotate(node, rest, axis, state[key] * Math.PI / 180);
    rotate(gear, gearRest, [0, 0, 1], -state.base_deg * Math.PI / 180);
    const travelMM = (85 - state.gripper_opening_mm) / 2;
    rotate(pinion, pinionRest, [0, 0, -1], travelMM / 9);
    jawA.position.copy(restA); jawA.position.y += travelMM / 1000;
    jawB.position.copy(restB); jawB.position.y -= travelMM / 1000;
    scene.updateMatrixWorld(true);
    return {...state};
  }

  setPose(REST_POSE);
  return {setPose, reset: () => setPose(REST_POSE), getPose: () => ({...state})};
}
