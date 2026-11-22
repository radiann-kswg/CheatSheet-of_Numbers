// node tools/check_wikipedia_katex.cjs <ビューアーと同じ katex.min.js のパス>
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");

function check(katex) {
    const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
    const version = html.match(/<script src="[^"]*\/katex@([^/"]+)\/dist\/katex\.min\.js"/)?.[1];
    if (!version || katex.version !== version) {
        throw new Error(`KaTeX の版が違います。ビューアー ${version} / 検査 ${katex.version}`);
    }

    let quotes = 0;
    let formulas = 0;
    let problems = 0;
    const numbers = path.join(root, "numbers");
    for (const group of fs.readdirSync(numbers, { withFileTypes: true })) {
        if (!group.isDirectory()) continue;
        for (const name of fs.readdirSync(path.join(numbers, group.name))) {
            if (!/^\d+\.md$/.test(name)) continue;
            const file = path.join("numbers", group.name, name);
            const lines = fs.readFileSync(path.join(root, file), "utf8").split(/\r?\n/);
            for (const [i, line] of lines.entries()) {
                if (!line.startsWith("- Wikipedia") || !/短い引用|原文照合・要約/.test(line)) continue;
                quotes++;
                const report = (message) => {
                    problems++;
                    console.error(`${file}:${i + 1} ${message}`);
                };
                const quote = line.match(/）: (.*)（出典:/u)?.[1];
                if (quote === undefined) {
                    report("引用本文と出典の境界を読み取れません");
                    continue;
                }
                // ビューアーと同じ $ / $$ 区切りで KaTeX に渡す。閉じ忘れた $ は本文側に残る。
                const prose = quote.replace(/(\$\$|\$)([^$]+?)\1/g, (_, delimiter, tex) => {
                    formulas++;
                    if (/(?:[+=^_×÷-]|\\(?:times|div|cdot))\s*$/u.test(tex)) {
                        report(`演算子の直後で終わる式 ${tex}`);
                    }
                    try {
                        katex.renderToString(tex, { displayMode: delimiter === "$$", throwOnError: true, strict: "error" });
                    } catch (error) {
                        report(`${tex} — ${error.message}`);
                    }
                    return "";
                });
                const unprotected = prose.match(/\\[A-Za-z]+/);
                if (unprotected) report(`数式の外にTeXコマンド ${unprotected[0]} が残っています`);
                if ((/短い引用・整形|原文照合・要約/.test(line) && prose.includes("$")) ||
                    /\$(?=[\\A-Za-z{]|\d+\s*[=+^_])/u.test(prose)) {
                    report("対応する数式区切りがありません");
                }
            }
        }
    }
    if (!quotes || !formulas) throw new Error("検査対象のWikipedia引用または数式がありません");
    console.log(`Wikipedia引用 ${quotes} 件、数式 ${formulas} 件、KaTeX ${katex.version}、問題 ${problems} 件`);
    return problems === 0;
}

try {
    const bundle = process.argv[2];
    if (!bundle) throw new Error("使い方: node tools/check_wikipedia_katex.cjs <katex.min.js>");
    if (!check(require(path.resolve(bundle)))) process.exitCode = 1;
} catch (error) {
    console.error(error.message);
    process.exitCode = 1;
}
