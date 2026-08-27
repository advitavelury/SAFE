// Pose templates in box-local space (0..1).
// Keys mirror a reduced MediaPipe Pose landmark set.
export const POSES = {
  standing: {
    head: [0.5, 0.09], neck: [0.5, 0.21],
    lSho: [0.33, 0.23], rSho: [0.67, 0.23],
    lElb: [0.27, 0.41], rElb: [0.73, 0.41],
    lWri: [0.25, 0.57], rWri: [0.75, 0.57],
    lHip: [0.39, 0.56], rHip: [0.61, 0.56],
    lKne: [0.38, 0.77], rKne: [0.62, 0.77],
    lAnk: [0.37, 0.96], rAnk: [0.63, 0.96],
  },
  sitting: {
    head: [0.5, 0.11], neck: [0.5, 0.25],
    lSho: [0.32, 0.27], rSho: [0.68, 0.27],
    lElb: [0.25, 0.46], rElb: [0.75, 0.46],
    lWri: [0.36, 0.61], rWri: [0.64, 0.61],
    lHip: [0.38, 0.64], rHip: [0.62, 0.64],
    lKne: [0.29, 0.79], rKne: [0.71, 0.79],
    lAnk: [0.31, 0.96], rAnk: [0.69, 0.96],
  },
  fallen: {
    head: [0.11, 0.42], neck: [0.23, 0.46],
    lSho: [0.26, 0.31], rSho: [0.26, 0.6],
    lElb: [0.4, 0.24], rElb: [0.39, 0.71],
    lWri: [0.53, 0.19], rWri: [0.51, 0.81],
    lHip: [0.61, 0.39], rHip: [0.61, 0.61],
    lKne: [0.78, 0.34], rKne: [0.78, 0.67],
    lAnk: [0.94, 0.29], rAnk: [0.94, 0.72],
  },
};

export const BONES = [
  ["head", "neck"], ["neck", "lSho"], ["neck", "rSho"],
  ["lSho", "lElb"], ["lElb", "lWri"], ["rSho", "rElb"], ["rElb", "rWri"],
  ["lSho", "lHip"], ["rSho", "rHip"], ["lHip", "rHip"],
  ["lHip", "lKne"], ["lKne", "lAnk"], ["rHip", "rKne"], ["rKne", "rAnk"],
];
