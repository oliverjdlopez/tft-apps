/** User-facing explanations for the supported HDBSCAN configuration. */
const distanceAmbiguity = "Measured in Euclidean distance units. Marks a board ambiguous when its two closest acceptable families differ by at most this amount. Increasing it flags more close contests without changing discovery clusters.";
const referenceRejection = "Maximum Euclidean structural distance allowed to the nearest saved family member. Lower values reject more boards; higher values accept looser matches during classification without changing discovered families.";

export const parameterHelp = {
  hdbscan: {
    min_cluster_size: "Smallest number of sampled boards that can form a density-based family. Larger values focus discovery on more common structures; smaller values allow rarer groups to survive.",
    min_samples: "Controls how much nearby evidence is required for a board to lie in a dense region. Larger values generally make discovery more conservative and label more boards as noise; smaller values admit sparser groups.",
    cluster_selection_method: "Chooses how families are selected from the density hierarchy: eom favors stable clusters, while leaf selects the finest terminal clusters.",
    cluster_selection_epsilon: "Euclidean-distance threshold for merging nearby density clusters during selection. Zero leaves selection to the chosen cluster-selection method.",
    allow_single_cluster: "Allows discovery to return one overall density cluster when the sample supports that result. Enable it when one broad family is a meaningful possible outcome; otherwise the root cluster is excluded from selection.",
    rejection_distance: referenceRejection,
    ambiguity_margin: distanceAmbiguity,
  },
};
