(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ReviewPilotDiffAnchor = api;
})(globalThis, function () {
  "use strict";

  function sha256Hex(ascii) {
    if (typeof require === "function") {
      try {
        return require("crypto").createHash("sha256").update(String(ascii), "utf8").digest("hex");
      } catch (err) {
        /* browser bundle */
      }
    }
    return sha256HexBrowser(String(ascii));
  }

  function sha256HexBrowser(ascii) {
    const mathPow = Math.pow;
    const maxWord = mathPow(2, 32);
    let result = "";
    const words = [];
    const asciiBitLength = ascii.length * 8;
    let hash = [];
    const k = [];
    let primeCounter = 0;
    const isComposite = {};
    for (let candidate = 2; primeCounter < 64; candidate += 1) {
      if (!isComposite[candidate]) {
        for (let i = 0; i < 313; i += candidate) {
          isComposite[i] = candidate;
        }
        hash[primeCounter] = (mathPow(candidate, 0.5) * maxWord) | 0;
        k[primeCounter++] = (mathPow(candidate, 1 / 3) * maxWord) | 0;
      }
    }
    ascii += "\x80";
    while (ascii.length % 64 - 56) ascii += "\x00";
    for (let i = 0; i < ascii.length; i += 1) {
      const j = ascii.charCodeAt(i);
      if (j >> 8) return "";
      words[i >> 2] |= j << (((3 - i) % 4) * 8);
    }
    words[words.length] = (asciiBitLength / maxWord) | 0;
    words[words.length] = asciiBitLength;
    for (let j = 0; j < words.length; ) {
      const w = words.slice(j, j += 16);
      const oldHash = hash.slice(0);
      for (let i = 0; i < 64; i += 1) {
        const w15 = w[i - 15];
        const w2 = w[i - 2];
        const a = hash[0];
        const e = hash[4];
        const temp1 =
          hash[7] +
          (rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25)) +
          ((e & hash[5]) ^ (~e & hash[6])) +
          k[i] +
          (w[i] =
            i < 16
              ? w[i]
              : (w[i - 16] +
                  (rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15 >>> 3)) +
                  w[i - 7] +
                  (rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2 >>> 10))) |
                0);
        const temp2 =
          (rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22)) +
          ((a & hash[1]) ^ (a & hash[2]) ^ (hash[1] & hash[2]));
        hash = [(temp1 + temp2) | 0].concat(hash);
        hash[4] = (hash[4] + temp1) | 0;
      }
      for (let i = 0; i < 8; i += 1) {
        hash[i] = (hash[i] + oldHash[i]) | 0;
      }
    }
    for (let i = 0; i < 8; i += 1) {
      for (let j = 3; j + 1; j -= 1) {
        const b = (hash[i] >> (j * 8)) & 255;
        result += (b < 16 ? "0" : "") + b.toString(16);
      }
    }
    return result;
  }

  function rightRotate(value, amount) {
    return (value >>> amount) | (value << (32 - amount));
  }

  function parsePrLabel(pr) {
    const match = /^([^/]+)\/([^#]+)#(\d+)$/.exec(String(pr || "").trim());
    if (!match) return null;
    return { owner: match[1], repo: match[2], number: match[3] };
  }

  function fileAnchorId(path) {
    if (!path) return "";
    const hash = sha256Hex(path);
    return hash ? "diff-" + hash : "";
  }

  function lineAnchorId(finding) {
    if (!finding || !finding.path) return "";
    return fileAnchorId(finding.path);
  }

  function lineHref(model, finding) {
    if (!model || !finding || !finding.path) return "";
    const pr = parsePrLabel(model.pr);
    if (!pr) return "";
    const anchorId = lineAnchorId(finding);
    if (!anchorId) return "";
    const params = [];
    if (model.issue) params.push("review_pilot_issue=" + encodeURIComponent(String(model.issue)));
    if (model.sha) params.push("review_pilot_sha=" + encodeURIComponent(String(model.sha)));
    const query = params.length ? "?" + params.join("&") : "";
    return (
      "https://github.com/" +
      pr.owner +
      "/" +
      pr.repo +
      "/pull/" +
      pr.number +
      "/changes" +
      query +
      "#" +
      anchorId
    );
  }

  return {
    sha256Hex: sha256Hex,
    fileAnchorId: fileAnchorId,
    lineAnchorId: lineAnchorId,
    lineHref: lineHref,
    parsePrLabel: parsePrLabel,
  };
});
