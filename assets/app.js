const docListEl = document.getElementById("doc-list");
const searchEl = document.getElementById("search");
const docViewEl = document.getElementById("doc-view");
const loreFiltersEl = document.getElementById("lore-filters");
const propertyFiltersEl = document.getElementById("property-filters");
const resultCountEl = document.getElementById("result-count");
const clearFiltersEl = document.getElementById("clear-filters");
const jumpEl = document.getElementById("jump");
const jumpRangeEl = document.getElementById("jump-range");
const jumpFormEl = document.getElementById("jump-form");

const state = {
	records: [],
	filters: { lore: [], properties: [] },
	selectedLore: new Set(),
	selectedProperties: new Set(),
	currentPath: "",
};
const visibleButtons = new Map();
let documentRequest = null;

const markdownRenderer = globalThis.marked?.Marked && globalThis.DOMPurify?.sanitize
	? new marked.Marked({ gfm: true, breaks: false })
	: null;

function normalizeDocPath(href, basePath) {
	if (!href || href.startsWith("http://") || href.startsWith("https://") || href.startsWith("#")) {
		return null;
	}
	if (!href.endsWith(".md")) {
		return null;
	}

	const baseDir = basePath.includes("/")
		? basePath.slice(0, basePath.lastIndexOf("/") + 1)
		: "";
	const resolved = new URL(href, `https://local/${baseDir}`).pathname;
	const path = resolved.replace(/^\//, "");

	if (!path.startsWith("numbers/") && path !== "index.md") {
		return null;
	}
	return path;
}

function renderMathIn(element) {
	// KaTeX auto-render（CDN が読み込めない場合は数式を素のまま表示）
	if (typeof renderMathInElement === "function") {
		renderMathInElement(element, {
			delimiters: [
				{ left: "$$", right: "$$", display: true },
				{ left: "$", right: "$", display: false },
			],
			throwOnError: false,
		});
	}
}

// --- 数式の保護 ---
// marked は数式内の `<`（HTMLタグと誤認→サニタイズで欠落）や `_` `*`（強調記法）を
// 壊してしまうため、Markdown 変換の前に $...$ / $$...$$ を退避し、変換後に戻す。
const MATH_TOKEN_PREFIX = "\uE000MATH";
const MATH_TOKEN_SUFFIX = "\uE001";

function extractMathSpans(markdown) {
	const spans = [];
	const pattern = /\$\$[\s\S]+?\$\$|\$[^$\n]+?\$/g;
	const replaced = markdown.replace(pattern, (match) => {
		const token = `${MATH_TOKEN_PREFIX}${spans.length}${MATH_TOKEN_SUFFIX}`;
		spans.push(match);
		return token;
	});
	return { replaced, spans };
}

function restoreMathSpans(element, spans) {
	if (spans.length === 0) {
		return;
	}
	const tokenPattern = new RegExp(`${MATH_TOKEN_PREFIX}(\\d+)${MATH_TOKEN_SUFFIX}`, "g");
	const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
	const targets = [];
	while (walker.nextNode()) {
		if (walker.currentNode.nodeValue.includes(MATH_TOKEN_PREFIX)) {
			targets.push(walker.currentNode);
		}
	}
	for (const node of targets) {
		node.nodeValue = node.nodeValue.replace(
			tokenPattern,
			(_all, index) => spans[Number(index)] ?? "",
		);
	}
}

function setupFilterGroup(container, filterDefs, selectedSet, onChange) {
	container.innerHTML = "";

	for (const filter of filterDefs) {
		const label = document.createElement("label");
		label.className = "chip";

		const input = document.createElement("input");
		input.type = "checkbox";
		input.value = filter.key;
		input.addEventListener("change", () => {
			if (input.checked) {
				selectedSet.add(filter.key);
			} else {
				selectedSet.delete(filter.key);
			}
			onChange();
		});

		const text = document.createElement("span");
		text.textContent = filter.label;

		label.appendChild(input);
		label.appendChild(text);
		container.appendChild(label);
	}
}

function matchesCategory(recordValues, selectedSet) {
	if (selectedSet.size === 0) {
		return true;
	}
	for (const key of selectedSet) {
		if (recordValues.includes(key)) {
			return true;
		}
	}
	return false;
}

function filterRecords(keyword, issue) {
	return state.records.filter((record) => {
		const issueOk = !issue || Boolean(record.issueSnippets?.[issue]);
		const keywordOk = !keyword || record.searchText.includes(keyword);
		const loreOk = matchesCategory(record.loreFilters, state.selectedLore);
		const propOk = matchesCategory(record.propertyFilters, state.selectedProperties);
		return issueOk && keywordOk && loreOk && propOk;
	});
}

function renderDocumentList(records, issue) {
	docListEl.innerHTML = "";
	visibleButtons.clear();
	resultCountEl.textContent = `${records.length}件`;

	if (records.length === 0) {
		const li = document.createElement("li");
		li.className = "empty";
		li.textContent = "一致する数字がありません。";
		docListEl.appendChild(li);
		return;
	}

	for (const record of records) {
		const li = document.createElement("li");
		const button = document.createElement("button");
		button.type = "button";
		visibleButtons.set(record.path, button);
		button.addEventListener("click", () => {
			loadDocument(record.path).catch(showError);
		});

		const title = document.createElement("strong");
		title.textContent = record.title;

		const meta = document.createElement("small");
		meta.textContent = record.issueSnippets?.[issue] || record.snippets[0] || "数秘・性質を表示";

		button.appendChild(title);
		button.appendChild(meta);
		li.appendChild(button);
		docListEl.appendChild(li);
	}
	markCurrentDocument(state.currentPath);
}

function markCurrentDocument(path) {
	const previous = visibleButtons.get(state.currentPath);
	previous?.classList.remove("active");
	previous?.removeAttribute("aria-current");
	const current = visibleButtons.get(path);
	current?.classList.add("active");
	current?.setAttribute("aria-current", "page");
	state.currentPath = path;
}

function renderListByCurrentFilters() {
	const query = searchEl.value.trim().toLowerCase();
	const prefix = /^(?:#|issue[:\s]+#?)(\d+)(?:\s+|$)/.exec(query);
	const issue = prefix?.[1];
	const keyword = prefix ? query.slice(prefix[0].length) : query;
	renderDocumentList(filterRecords(keyword, issue), issue);
}

function renderMarkdownSource(markdown, path) {
	const source = document.createElement("pre");
	source.className = "markdown-source";
	let offset = 0;
	// プレーンテキストのまま、リポジトリ内の Markdown リンクだけを開けるようにする。
	for (const match of markdown.matchAll(/\[[^\]\n]+\]\(((?:[\w.-]+\/)*[\w.-]+\.md)\)/g)) {
		if (!normalizeDocPath(match[1], path)) {
			continue;
		}
		const link = document.createElement("a");
		link.setAttribute("href", match[1]);
		link.textContent = match[0];
		source.append(markdown.slice(offset, match.index), link);
		offset = match.index + match[0].length;
	}
	source.append(markdown.slice(offset));
	docViewEl.replaceChildren(source);
}

async function loadDocument(path) {
	documentRequest?.abort();
	const request = new AbortController();
	documentRequest = request;
	let markdown;
	try {
		const response = await fetch(path, { signal: request.signal });
		if (!response.ok) {
			throw new Error(`読み込みに失敗しました: ${path}`);
		}
		markdown = await response.text();
	} catch (error) {
		if (!request.signal.aborted) {
			showError(error);
		}
		return;
	}
	if (request.signal.aborted) {
		return;
	}
	if (markdownRenderer) {
		const { replaced, spans } = extractMathSpans(markdown);
		const html = markdownRenderer.parse(replaced);
		docViewEl.innerHTML = DOMPurify.sanitize(html);
		restoreMathSpans(docViewEl, spans);
		renderMathIn(docViewEl);
	} else {
		renderMarkdownSource(markdown, path);
	}
	markCurrentDocument(path);

	history.replaceState({}, "", `#${encodeURIComponent(path)}`);

	docViewEl.querySelectorAll("a").forEach((anchor) => {
		const href = anchor.getAttribute("href");
		const target = normalizeDocPath(href, path);
		if (!target) {
			return;
		}
		anchor.addEventListener("click", (event) => {
			event.preventDefault();
			loadDocument(target).catch(showError);
		});
	});
}

function showError(error) {
	markCurrentDocument("");
	docViewEl.textContent = `表示に失敗しました: ${error.message}`;
}

async function bootstrap() {
	jumpFormEl.addEventListener("submit", (event) => {
		event.preventDefault();
		const record = state.records.find((r) => r.n === jumpEl.valueAsNumber);
		if (record) {
			loadDocument(record.path).catch(showError);
		}
	});

	const response = await fetch("assets/numbers-index.json");
	if (!response.ok) {
		throw new Error("assets/numbers-index.json の読み込みに失敗しました。");
	}

	const data = await response.json();
	state.records = data.numbers || [];
	state.filters = data.filters || { lore: [], properties: [] };
	if (state.records.length > 0) {
		jumpEl.max = state.records[state.records.length - 1].n;
		jumpRangeEl.textContent = `（${jumpEl.min}〜${jumpEl.max}）`;
	}

	setupFilterGroup(loreFiltersEl, state.filters.lore, state.selectedLore, renderListByCurrentFilters);
	setupFilterGroup(
		propertyFiltersEl,
		state.filters.properties,
		state.selectedProperties,
		renderListByCurrentFilters,
	);

	searchEl.addEventListener("input", renderListByCurrentFilters);
	clearFiltersEl.addEventListener("click", () => {
		state.selectedLore.clear();
		state.selectedProperties.clear();
		searchEl.value = "";
		document
			.querySelectorAll(".chip input[type='checkbox']")
			.forEach((input) => {
				input.checked = false;
			});
		renderListByCurrentFilters();
	});

	renderListByCurrentFilters();

	const hashPath = decodeURIComponent(location.hash.replace(/^#/, ""));
	const initial =
		state.records.find((record) => record.path === hashPath) ||
		state.records[0];

	if (initial) {
		await loadDocument(initial.path);
	}
}

bootstrap().catch(showError);
