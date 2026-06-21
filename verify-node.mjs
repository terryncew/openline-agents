#!/usr/bin/env node
// Independent Node verifier for Python-issued OpenLine Agents receipts.

import fs from "node:fs";
import { createHash, createPublicKey, verify as ed25519Verify } from "node:crypto";

const SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");
const HEX64 = /^[0-9a-f]{64}$/;
const HEX128 = /^[0-9a-f]{128}$/;

function parseJsonStrict(text) {
  let offset = 0;
  const skip = () => { while (/[\t\n\r ]/.test(text[offset] ?? "")) offset += 1; };
  const string = () => {
    if (text[offset] !== '"') throw new Error("expected string");
    const start = offset++;
    let escaped = false;
    while (offset < text.length) {
      const char = text[offset++];
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') return JSON.parse(text.slice(start, offset));
    }
    throw new Error("unterminated string");
  };
  const value = () => {
    skip();
    if (text[offset] === '"') return string();
    if (text[offset] === "{") {
      offset += 1;
      const result = Object.create(null);
      const keys = new Set();
      skip();
      if (text[offset] === "}") { offset += 1; return result; }
      while (true) {
        skip();
        const key = string();
        if (keys.has(key)) throw new Error(`duplicate key ${key}`);
        keys.add(key);
        skip();
        if (text[offset++] !== ":") throw new Error("expected colon");
        result[key] = value();
        skip();
        const delimiter = text[offset++];
        if (delimiter === "}") return result;
        if (delimiter !== ",") throw new Error("expected comma");
      }
    }
    if (text[offset] === "[") {
      offset += 1;
      const result = [];
      skip();
      if (text[offset] === "]") { offset += 1; return result; }
      while (true) {
        result.push(value());
        skip();
        const delimiter = text[offset++];
        if (delimiter === "]") return result;
        if (delimiter !== ",") throw new Error("expected comma");
      }
    }
    for (const [word, parsed] of [["true", true], ["false", false], ["null", null]]) {
      if (text.startsWith(word, offset)) { offset += word.length; return parsed; }
    }
    const match = /^-?(?:0|[1-9][0-9]*)/.exec(text.slice(offset));
    if (!match) throw new Error("invalid JSON value");
    offset += match[0].length;
    const parsed = Number(match[0]);
    if (!Number.isSafeInteger(parsed)) throw new Error("unsafe integer");
    return parsed;
  };
  const result = value();
  skip();
  if (offset !== text.length) throw new Error("trailing JSON");
  return result;
}

function quoteAscii(value) {
  let output = '"';
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code === 8) output += "\\b";
    else if (code === 9) output += "\\t";
    else if (code === 10) output += "\\n";
    else if (code === 12) output += "\\f";
    else if (code === 13) output += "\\r";
    else if (code === 34) output += '\\"';
    else if (code === 92) output += "\\\\";
    else if (code < 32 || code > 126) output += `\\u${code.toString(16).padStart(4, "0")}`;
    else output += String.fromCharCode(code);
  }
  return `${output}"`;
}

function encode(value) {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "string") return quoteAscii(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("unsafe canonical number");
    return Object.is(value, -0) ? "0" : String(value);
  }
  if (Array.isArray(value)) return `[${value.map(encode).join(",")}]`;
  if (typeof value !== "object") throw new Error("unsupported canonical value");
  for (const key of Object.keys(value)) if (!/^[\x00-\x7f]*$/.test(key)) throw new Error("non-ASCII key");
  return `{${Object.keys(value).sort().map((key) => `${quoteAscii(key)}:${encode(value[key])}`).join(",")}}`;
}

function exact(value, fields) {
  if (Object.keys(value).sort().join("\0") !== [...fields].sort().join("\0")) throw new Error("field mismatch");
}

function verifyEnvelope(receipt) {
  const { payload_hash: payloadHash, signature, ...body } = receipt;
  exact(signature, ["algorithm", "public_key", "value"]);
  if (!HEX64.test(payloadHash) || signature.algorithm !== "Ed25519" || !HEX64.test(signature.public_key) || !HEX128.test(signature.value)) return false;
  const bytes = Buffer.from(encode(body), "ascii");
  if (createHash("sha256").update(bytes).digest("hex") !== payloadHash) return false;
  const key = createPublicKey({ key: Buffer.concat([SPKI_PREFIX, Buffer.from(signature.public_key, "hex")]), format: "der", type: "spki" });
  return ed25519Verify(null, bytes, key, Buffer.from(signature.value, "hex"));
}

const fields = {
  outcome_receipt: ["kind", "receipt_version", "algorithm_id", "canonicalization_id", "spec_uri", "attestation", "input_receipt_hash", "input_trace_id", "label", "score_micros", "label_schema_id", "evidence_hash", "witness_id", "observed_at_unix_micros", "payload_hash", "signature"],
  tc_calibration_profile_receipt: ["kind", "receipt_version", "algorithm_id", "canonicalization_id", "spec_uri", "attestation", "profile_id", "measurement_algorithm_id", "fit_method_id", "thresholds", "training_corpus_hash", "holdout_corpus_hash", "training_sample_count", "holdout_sample_count", "criteria", "validation", "activation_status", "payload_hash", "signature"],
  tc_controller_proposal_receipt: ["kind", "receipt_version", "algorithm_id", "canonicalization_id", "spec_uri", "attestation", "mode", "action", "input_receipt_hash", "measurement_receipt_hash", "outcome_receipt_hash", "calibration_profile_hash", "previous_proposal_hash", "reasons", "payload_hash", "signature"],
};

function load(path) { return parseJsonStrict(fs.readFileSync(path, "utf8")); }
function verify(path) {
  const receipt = load(path);
  exact(receipt, fields[receipt.kind]);
  if (!verifyEnvelope(receipt)) throw new Error(`${path}: signature failed`);
}

for (const name of ["outcome-receipt.json", "calibration-profile-receipt.json", "controller-proposal-receipt.json"]) verify(`vectors/${name}`);
if (verifyEnvelope(load("vectors/invalid-tampered-controller-proposal.json"))) throw new Error("tampered proposal accepted");
console.log("OpenLine Agents Node conformance: 3 valid receipts accepted; tampering rejected");
