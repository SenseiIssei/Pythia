//! Gradient-boosted trees from LightGBM's own JSON dump (`booster.dump_model()`).
//!
//! Why not ONNX here: for tree ensembles this walker is exact, has no native
//! runtime to ship in the desktop bundle, and fits on one screen. ONNX stays
//! the format for the neural models that may come later.
//!
//! The split rule mirrors LightGBM's `NumericalDecision` (src/io/tree.h):
//! a NaN input counts as 0.0 unless the split handles NaN itself; a split whose
//! missing type matches the input goes the stored default way; otherwise
//! `value <= threshold` goes left. Inputs are rounded through f32 first, because
//! the lab trains on float32 matrices and the thresholds sit between float32
//! values.

use serde_json::Value;

use crate::MlError;

const ZERO_THRESHOLD: f64 = 1e-35;

#[derive(Debug, Clone, Copy, PartialEq)]
enum Missing {
    None,
    Zero,
    NaN,
}

/// One tree, flattened. Children >= 0 are node indices, < 0 are `!leaf_index`.
#[derive(Debug, Clone)]
struct Tree {
    feature: Vec<u32>,
    threshold: Vec<f64>,
    missing: Vec<Missing>,
    default_left: Vec<bool>,
    left: Vec<i32>,
    right: Vec<i32>,
    leaf: Vec<f64>,
}

#[derive(Debug, Clone)]
pub struct Gbdt {
    trees: Vec<Tree>,
    pub n_features: usize,
    pub feature_names: Vec<String>,
}

impl Gbdt {
    pub fn from_json(text: &str) -> Result<Self, MlError> {
        let v: Value = serde_json::from_str(text).map_err(|e| MlError::Format(e.to_string()))?;
        Self::from_value(&v)
    }

    pub fn from_value(v: &Value) -> Result<Self, MlError> {
        let objective = v.get("objective").and_then(Value::as_str).unwrap_or("");
        // Regression and ranking both answer with the raw sum of leaves; a
        // ranker's score has no unit, only its order within a group means anything.
        if !(objective.starts_with("regression") || objective.starts_with("lambdarank") || objective.starts_with("rank_xendcg")) {
            return Err(MlError::Format(format!("unsupported objective {objective:?}")));
        }
        if v.get("num_tree_per_iteration").and_then(Value::as_u64) != Some(1) {
            return Err(MlError::Format("only single-output models are supported".into()));
        }
        let feature_names: Vec<String> = v
            .get("feature_names")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect())
            .unwrap_or_default();
        let n_features = v
            .get("max_feature_idx")
            .and_then(Value::as_u64)
            .map(|m| m as usize + 1)
            .ok_or_else(|| MlError::Format("missing max_feature_idx".into()))?;
        let infos = v
            .get("tree_info")
            .and_then(Value::as_array)
            .ok_or_else(|| MlError::Format("missing tree_info".into()))?;
        let trees = infos
            .iter()
            .map(|t| {
                let root = t
                    .get("tree_structure")
                    .ok_or_else(|| MlError::Format("tree without structure".into()))?;
                build_tree(root, n_features)
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self { trees, n_features, feature_names })
    }

    pub fn n_trees(&self) -> usize {
        self.trees.len()
    }

    /// Raw model output. `x` must hold `n_features` values in training order;
    /// NaN means missing.
    pub fn predict(&self, x: &[f64]) -> f64 {
        debug_assert_eq!(x.len(), self.n_features);
        let x32: Vec<f64> = x.iter().map(|&v| v as f32 as f64).collect();
        self.trees.iter().map(|t| t.eval(&x32)).sum()
    }
}

impl Tree {
    fn eval(&self, x: &[f64]) -> f64 {
        if self.feature.is_empty() {
            return self.leaf[0];
        }
        let mut node = 0i32;
        loop {
            let i = node as usize;
            let mut v = x[self.feature[i] as usize];
            let miss = self.missing[i];
            if v.is_nan() && miss != Missing::NaN {
                v = 0.0;
            }
            let go_left = if (miss == Missing::Zero && v.abs() <= ZERO_THRESHOLD) || (miss == Missing::NaN && v.is_nan()) {
                self.default_left[i]
            } else {
                v <= self.threshold[i]
            };
            node = if go_left { self.left[i] } else { self.right[i] };
            if node < 0 {
                return self.leaf[(!node) as usize];
            }
        }
    }
}

fn build_tree(root: &Value, n_features: usize) -> Result<Tree, MlError> {
    let mut t = Tree {
        feature: vec![],
        threshold: vec![],
        missing: vec![],
        default_left: vec![],
        left: vec![],
        right: vec![],
        leaf: vec![],
    };
    if root.get("leaf_value").is_some() {
        t.leaf.push(num(root, "leaf_value")?);
        return Ok(t);
    }
    add_node(root, &mut t, n_features)?;
    Ok(t)
}

/// Appends a node (split or leaf) and returns its child reference.
fn add_node(n: &Value, t: &mut Tree, n_features: usize) -> Result<i32, MlError> {
    if n.get("leaf_value").is_some() {
        t.leaf.push(num(n, "leaf_value")?);
        return Ok(!((t.leaf.len() - 1) as i32));
    }
    let decision = n.get("decision_type").and_then(Value::as_str).unwrap_or("");
    if decision != "<=" {
        return Err(MlError::Format(format!("unsupported split {decision:?} (categorical splits are not handled)")));
    }
    let feature = n
        .get("split_feature")
        .and_then(Value::as_u64)
        .ok_or_else(|| MlError::Format("split without feature".into()))? as usize;
    if feature >= n_features {
        return Err(MlError::Format(format!("split on feature {feature} of {n_features}")));
    }
    let missing = match n.get("missing_type").and_then(Value::as_str) {
        Some("None") => Missing::None,
        Some("Zero") => Missing::Zero,
        Some("NaN") => Missing::NaN,
        other => return Err(MlError::Format(format!("unknown missing_type {other:?}"))),
    };
    let idx = t.feature.len();
    t.feature.push(feature as u32);
    t.threshold.push(num(n, "threshold")?);
    t.missing.push(missing);
    t.default_left.push(n.get("default_left").and_then(Value::as_bool).unwrap_or(true));
    t.left.push(0);
    t.right.push(0);
    let l = add_node(n.get("left_child").ok_or_else(|| MlError::Format("split without left child".into()))?, t, n_features)?;
    let r = add_node(n.get("right_child").ok_or_else(|| MlError::Format("split without right child".into()))?, t, n_features)?;
    t.left[idx] = l;
    t.right[idx] = r;
    Ok(idx as i32)
}

fn num(n: &Value, key: &str) -> Result<f64, MlError> {
    n.get(key).and_then(Value::as_f64).ok_or_else(|| MlError::Format(format!("missing {key}")))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stump(missing: &str, default_left: bool) -> Gbdt {
        let j = format!(
            r#"{{"objective":"regression","num_tree_per_iteration":1,"max_feature_idx":0,"feature_names":["a"],
            "tree_info":[{{"tree_structure":{{"split_feature":0,"threshold":1.5,"decision_type":"<=",
            "default_left":{default_left},"missing_type":"{missing}",
            "left_child":{{"leaf_value":-1.0}},"right_child":{{"leaf_value":2.0}}}}}}]}}"#
        );
        Gbdt::from_json(&j).unwrap()
    }

    #[test]
    fn plain_split() {
        let m = stump("None", true);
        assert_eq!(m.predict(&[1.0]), -1.0);
        assert_eq!(m.predict(&[1.5]), -1.0);
        assert_eq!(m.predict(&[1.6]), 2.0);
    }

    #[test]
    fn nan_becomes_zero_unless_the_split_handles_it() {
        // missing_type None: NaN is treated as 0.0, and 0.0 <= 1.5 goes left
        assert_eq!(stump("None", false).predict(&[f64::NAN]), -1.0);
        // missing_type NaN: NaN follows default_left, even when 0.0 would go the other way
        assert_eq!(stump("NaN", false).predict(&[f64::NAN]), 2.0);
        assert_eq!(stump("NaN", true).predict(&[f64::NAN]), -1.0);
    }

    #[test]
    fn zero_missing_type() {
        assert_eq!(stump("Zero", false).predict(&[0.0]), 2.0);
        assert_eq!(stump("Zero", false).predict(&[1.0]), -1.0);
    }

    #[test]
    fn accepts_a_ranker() {
        let j = r#"{"objective":"lambdarank","num_tree_per_iteration":1,"max_feature_idx":0,
            "tree_info":[{"tree_structure":{"leaf_value":0.25}}]}"#;
        assert_eq!(Gbdt::from_json(j).unwrap().predict(&[1.0]), 0.25);
    }

    #[test]
    fn rejects_what_it_cannot_evaluate() {
        let j = r#"{"objective":"binary","num_tree_per_iteration":1,"max_feature_idx":0,"tree_info":[]}"#;
        assert!(Gbdt::from_json(j).is_err());
    }
}
