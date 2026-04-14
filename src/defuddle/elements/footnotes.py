"""Footnote standardization ported from JS defuddle/src/elements/footnotes.ts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup, NavigableString, Tag

# Matches heading text for loose footnote section delimiters
_FOOTNOTE_SECTION_RE = re.compile(
    r"^(foot\s*notes?|end\s*notes?|notes?|references?)$", re.IGNORECASE
)

FOOTNOTE_LIST_SELECTORS = ", ".join([
    "div.footnote ol",
    "div.footnotes ol",
    "div[role='doc-endnotes']",
    "div[role='doc-footnotes']",
    "ol.footnotes-list",
    "ol.footnotes",
    "ol.references",
    "ol[class*='article-references']",
    "section.footnotes ol",
    "section[role='doc-endnotes']",
    "section[role='doc-bibliography']",
    "section[role='doc-footnotes']",
    "ul.footnotes-list",
    "ul.ltx_biblist",
    "div.footnotes-footer",
    "div[data-component-name='FootnoteToDOM']",
])

FOOTNOTE_INLINE_REFERENCES = ", ".join([
    "sup.reference",
    "cite.ltx_cite",
    "sup[id^='fnr']",
    "span[id^='fnr']",
    "span[class*='footnote_ref']",
    "span[class*='footnote-ref']",
    "span.footnote-link",
    "a.citation",
    "a[id^='ref-link']",
    "a[href^='#fn']",
    "sup.footnoteref",
    "a.footnote-anchor",
    "span.footnote-hovercard-target a",
    "span.footnote-reference",
    "sup[class*='aside-link']",
])


@dataclass
class FootnoteData:
    content: Any  # Tag or string
    original_id: str
    refs: list[str] = field(default_factory=list)


def process_footnotes(element: Tag, doc: BeautifulSoup) -> None:
    """Standardize all footnotes in the element, matching JS behavior."""
    handler = FootnoteHandler(doc)
    handler.standardize_footnotes(element)


class FootnoteHandler:
    def __init__(self, doc: BeautifulSoup) -> None:
        self.doc = doc
        self.generic_container: Optional[Tag] = None
        self.generic_elements: list[Tag] = []
        self.extra_containers_to_remove: list[Tag] = []

    def create_footnote_reference(self, footnote_number: str, ref_id: str) -> Tag:
        """Create a standardized <sup id="refId"><a href="#fn:N">N</a></sup>."""
        sup = self.doc.new_tag("sup")
        sup["id"] = ref_id
        link = self.doc.new_tag("a")
        link["href"] = f"#fn:{footnote_number}"
        link.string = footnote_number
        sup.append(link)
        return sup

    def create_footnote_item(
        self, footnote_number: int, content: Any, refs: list[str]
    ) -> Tag:
        """Create a standardized <li id="fn:N" class="footnote"> element."""
        new_item = self.doc.new_tag("li")
        new_item["id"] = f"fn:{footnote_number}"

        if isinstance(content, str):
            paragraph = self.doc.new_tag("p")
            soup = BeautifulSoup(content, "html.parser")
            for child in list(soup.children):
                child.extract()
                paragraph.append(child)
            new_item.append(paragraph)
        elif isinstance(content, Tag):
            if content.name == "cite":
                paragraph = self.doc.new_tag("p")
                parsed = BeautifulSoup(str(content), "html.parser")
                cite = parsed.find("cite")
                if cite is not None:
                    paragraph.append(cite)
                self._remove_backrefs(paragraph)
                new_item.append(paragraph)
                return new_item
            block_tags = {
                "div", "section", "article", "aside", "blockquote",
                "dl", "figure", "footer", "form", "h1", "h2", "h3",
                "h4", "h5", "h6", "header", "hr", "main", "nav",
                "ol", "p", "pre", "table", "ul",
            }
            children = [c for c in content.children if isinstance(c, Tag)]
            has_paragraphs = any(c.name == "p" for c in children)
            has_block_children = any(c.name in block_tags for c in children)

            if not has_paragraphs and not has_block_children:
                paragraph = self.doc.new_tag("p")
                self._transfer_content(content, paragraph)
                self._remove_backrefs(paragraph)
                new_item.append(paragraph)
            elif not has_paragraphs and has_block_children:
                for child in children:
                    clone = self._clone_tag(child)
                    self._remove_backrefs(clone)
                    new_item.append(clone)
            else:
                for child in children:
                    if child.name == "p":
                        text = child.get_text(strip=True)
                        if not text and not child.find(["img", "br"]):
                            continue
                        new_p = self.doc.new_tag("p")
                        self._transfer_content(child, new_p)
                        self._remove_backrefs(new_p)
                        new_item.append(new_p)
                    else:
                        clone = self._clone_tag(child)
                        self._remove_backrefs(clone)
                        new_item.append(clone)

        return new_item

    def collect_footnotes(self, element: Tag) -> dict[int, FootnoteData]:
        """Collect footnotes from footnote lists and generic containers."""
        footnotes: dict[int, FootnoteData] = {}
        footnote_count = 1
        processed_ids: set[str] = set()

        # Collect from footnote list selectors
        footnote_lists = element.select(FOOTNOTE_LIST_SELECTORS)
        for list_el in footnote_lists:
            # Wikidot: div.footnotes-footer with div.footnote-footer
            if list_el.has_attr("class") and "footnotes-footer" in list_el.get("class", []):
                footnote_divs = list_el.select("div.footnote-footer")
                for div in footnote_divs:
                    div_id = div.get("id", "")
                    match = re.match(r"^footnote-(\d+)$", div_id)
                    if match:
                        id_str = match.group(1)
                        if id_str not in processed_ids:
                            clone = self._clone_tag(div)
                            backlink = clone.find("a")
                            if backlink:
                                backlink.decompose()
                            text = clone.decode_contents()
                            text = re.sub(r"^\s*\.\s*", "", text)
                            content_div = self.doc.new_tag("div")
                            soup = BeautifulSoup(text.strip(), "html.parser")
                            for child in list(soup.children):
                                child.extract()
                                content_div.append(child)
                            footnotes[footnote_count] = FootnoteData(
                                content=content_div, original_id=id_str, refs=[]
                            )
                            processed_ids.add(id_str)
                            footnote_count += 1
                continue

            # Hugo/org-mode: div.footnote-definitions
            if list_el.has_attr("class") and "footnote-definitions" in list_el.get("class", []):
                defs = list_el.select("div.footnote-definition")
                for defn in defs:
                    sup_el = defn.select_one("sup[id]")
                    body = defn.select_one(".footnote-body")
                    if not sup_el or not body:
                        continue
                    id_val = (sup_el.get("id", "") or "").lower()
                    if not id_val or id_val in processed_ids:
                        continue
                    footnotes[footnote_count] = FootnoteData(
                        content=self._clone_tag(body), original_id=id_val, refs=[]
                    )
                    processed_ids.add(id_val)
                    footnote_count += 1
                parent = list_el.parent
                if parent and parent is not element and parent.get("class") and "footnotes" in parent.get("class", []):
                    self.extra_containers_to_remove.append(parent)
                continue

            # Substack
            if list_el.name == "div" and list_el.has_attr("data-component-name") and list_el.get("data-component-name") == "FootnoteToDOM":
                anchor = list_el.select_one("a.footnote-number")
                content_el = list_el.select_one(".footnote-content")
                if anchor and content_el:
                    id_val = anchor.get("id", "").replace("footnote-", "").lower()
                    if id_val and id_val not in processed_ids:
                        footnotes[footnote_count] = FootnoteData(
                            content=content_el, original_id=id_val, refs=[]
                        )
                        processed_ids.add(id_val)
                        footnote_count += 1
                continue

            # Common format: OL/UL with LI
            items = list_el.select("li, div[role='listitem']")
            for li in items:
                id_val = ""
                content: Any = None

                # Citations with .citations class
                citations_div = li.select_one(".citations")
                if citations_div and isinstance(citations_div, Tag):
                    cid = citations_div.get("id", "").lower()
                    if cid and cid.startswith("r"):
                        id_val = cid
                        citation_content = citations_div.select_one(".citation-content")
                        if citation_content:
                            content = citation_content

                if not id_val:
                    li_id = li.get("id", "").lower()
                    if li_id.startswith("bib.bib"):
                        id_val = li_id.replace("bib.bib", "")
                    elif li_id.startswith("fn:"):
                        id_val = li_id.replace("fn:", "")
                    elif li_id.startswith("fn"):
                        id_val = re.sub(r"^fn", "", li_id)
                    elif li.has_attr("data-counter"):
                        dc = li.get("data-counter", "")
                        id_val = re.sub(r"\.$", "", dc).lower()
                    else:
                        match = re.search(r"cite_note-(.+)", li.get("id", ""))
                        id_val = match.group(1).lower() if match else li_id
                    reference_text = li.select_one(".reference-text")
                    if isinstance(reference_text, Tag):
                        reference_clone = self._clone_tag(reference_text)
                        for backref in list(reference_clone.select(".mw-cite-backlink")):
                            backref.decompose()
                        for span in list(reference_clone.select(".reference-accessdate, .nowrap")):
                            span.unwrap()
                        reference_cite = reference_clone.find("cite")
                        content = reference_cite if isinstance(reference_cite, Tag) else reference_clone
                    else:
                        content = li

                if id_val and id_val not in processed_ids:
                    footnotes[footnote_count] = FootnoteData(
                        content=content or li, original_id=id_val, refs=[]
                    )
                    processed_ids.add(id_val)
                    footnote_count += 1

        # Generic fallback: ID-based detection
        if footnote_count == 1:
            candidate_refs: dict[str, list[Tag]] = {}
            for a in element.select('a[href*="#"]'):
                if not isinstance(a, Tag):
                    continue
                href = a.get("href", "")
                fragment = href.split("#")[-1].lower() if "#" in href else ""
                if not fragment:
                    continue
                text = a.get_text(strip=True)
                if not re.match(r"^\[?\(?\d{1,4}\)?\]?$", text):
                    continue
                candidate_refs.setdefault(fragment, []).append(a)

            if len(candidate_refs) >= 2:
                fragment_set = set(candidate_refs.keys())
                containers = element.select("div, section, aside, footer, ol, ul")
                best_container: Optional[Tag] = None
                best_match_count = 0

                for container in containers:
                    if container is element:
                        continue
                    match_count = len(self._find_matching_footnote_elements(container, fragment_set))
                    if match_count >= 2 and match_count >= best_match_count:
                        best_match_count = match_count
                        best_container = container

                if best_container is not None:
                    ordered = self._find_matching_footnote_elements(best_container, fragment_set)
                    footnote_fragments = {item_id for _, item_id in ordered}
                    external_total = 0
                    external_match = 0
                    for frag, anchors in candidate_refs.items():
                        if any(best_container in a.parents for a in anchors):
                            continue
                        external_total += 1
                        if frag in footnote_fragments:
                            external_match += 1
                    if external_match < max(2, -(-external_total * 75 // 100)):
                        best_container = None

                if best_container is not None:
                    for el, item_id in ordered:
                        if item_id in processed_ids:
                            continue
                        content_div = self.doc.new_tag("div")
                        clone = self._clone_tag(el)

                        # Remove id anchor marker
                        id_anchor = clone.select_one(f'a[id="{item_id}"]')
                        if id_anchor and (not id_anchor.get_text(strip=True) or re.match(r"^\d+[.)]*\s*$", id_anchor.get_text(strip=True))):
                            id_anchor.decompose()

                        named_anchor = clone.select_one("a[name]")
                        if named_anchor and named_anchor.get("name", "").lower() == item_id:
                            named_anchor.decompose()

                        first_text = next((c for c in clone.children if isinstance(c, NavigableString)), None)
                        if first_text:
                            new_val = re.sub(r"^\d+\.\s*", "", str(first_text))
                            first_text.replace_with(NavigableString(new_val))

                        if clone.name == "li":
                            self._transfer_content(clone, content_div)
                        else:
                            content_div.append(clone)

                        # Multi-paragraph footnotes
                        sibling = el.next_sibling
                        while sibling:
                            if isinstance(sibling, Tag):
                                if sibling.get("id"):
                                    break
                                sib_anchor_id = self._get_child_anchor_id(sibling)
                                if sib_anchor_id and sib_anchor_id in fragment_set:
                                    break
                                content_div.append(self._clone_tag(sibling))
                            sibling = sibling.next_sibling

                        footnotes[footnote_count] = FootnoteData(
                            content=content_div, original_id=item_id, refs=[]
                        )
                        processed_ids.add(item_id)
                        footnote_count += 1

                    self.generic_container = best_container

        # Microsoft Word HTML
        if footnote_count == 1:
            word_backrefs = [a for a in element.select('a[href*="#_ftnref"]') if isinstance(a, Tag)]
            if len(word_backrefs) >= 2:
                pairs: list[tuple[int, Tag]] = []
                for anchor in word_backrefs:
                    href = anchor.get("href", "")
                    fragment = href.split("#")[-1] if "#" in href else ""
                    match = re.match(r"^_ftnref(\d+)$", fragment)
                    if match:
                        pairs.append((int(match.group(1)), anchor))
                pairs.sort(key=lambda x: x[0])

                for num, anchor in pairs:
                    original_id = f"_ftn{num}"
                    if original_id in processed_ids:
                        continue
                    container = anchor.parent
                    while container and container is not element:
                        if container.name in ("p", "div", "li"):
                            break
                        container = container.parent
                    if not container or container is element:
                        continue

                    clone = self._clone_tag(container)
                    backref_a = clone.select_one('a[href*="_ftnref"]')
                    if backref_a:
                        wrap_sup = backref_a.find_parent("sup")
                        if wrap_sup:
                            wrap_sup.decompose()
                        else:
                            backref_a.decompose()

                    content_div = self.doc.new_tag("div")
                    content_div.append(clone)
                    footnotes[num] = FootnoteData(
                        content=content_div, original_id=original_id, refs=[]
                    )
                    processed_ids.add(original_id)
                    if num >= footnote_count:
                        footnote_count = num + 1
                    self.generic_elements.append(container)

        # Loose footnotes
        if footnote_count == 1:
            result = self._find_loose_footnote_paragraphs(element)
            if result:
                paragraphs, to_remove = result
                for i, (num, def_para) in enumerate(paragraphs):
                    next_def = paragraphs[i + 1][1] if i + 1 < len(paragraphs) else None
                    id_val = str(num)
                    if id_val in processed_ids:
                        continue
                    content_div = self.doc.new_tag("div")
                    p_clone = self._clone_tag(def_para)
                    marker = p_clone.find(True)
                    if marker and marker.name in ("sup", "strong"):
                        marker.decompose()
                        first_node = p_clone.contents[0] if p_clone.contents else None
                        if isinstance(first_node, NavigableString):
                            first_node.replace_with(NavigableString(str(first_node).lstrip()))
                    content_div.append(p_clone)

                    sibling = def_para.next_sibling
                    while sibling and sibling is not next_def:
                        if isinstance(sibling, Tag):
                            content_div.append(self._clone_tag(sibling))
                        sibling = sibling.next_sibling

                    footnotes[footnote_count] = FootnoteData(
                        content=content_div, original_id=id_val, refs=[]
                    )
                    processed_ids.add(id_val)
                    footnote_count += 1

                self.generic_elements.extend(to_remove)

        return footnotes

    def collect_inline_sidenotes(self, element: Tag) -> dict[int, FootnoteData]:
        """Handle CSS sidenote footnotes (Tufte-style, inline-footnote)."""
        footnotes: dict[int, FootnoteData] = {}
        containers = element.select(
            "span.footnote-container, span.sidenote-container, span.inline-footnote"
        )

        if not containers:
            ref_map: dict[str, tuple[int, Tag]] = {}
            footnote_count = 1
            for ref in element.select("sup.footnote-reference"):
                if not isinstance(ref, Tag):
                    continue
                link = ref.find("a", href=True)
                if not link or not isinstance(link, Tag):
                    continue
                href = str(link.get("href", ""))
                frag = href.split("#")[-1] if "#" in href else ""
                if not frag:
                    continue
                sidenote = ref.find_next_sibling("span", class_="sidenote")
                if not sidenote or not isinstance(sidenote, Tag):
                    continue
                content_clone = self._clone_tag(sidenote)
                for num_el in content_clone.select(".sidenote-number"):
                    num_el.decompose()
                num_match = re.search(r"(\d+)$", frag)
                footnote_number = num_match.group(1) if num_match else str(footnote_count)
                ref_id = f"fnref:{footnote_number}"
                footnotes[footnote_count] = FootnoteData(
                    content=content_clone,
                    original_id=footnote_number,
                    refs=[ref_id],
                )
                ref.replace_with(self.create_footnote_reference(footnote_number, ref_id))
                sidenote.decompose()
                for container in element.select("div.footnotes, div.footnote-definitions"):
                    if container not in self.extra_containers_to_remove:
                        self.extra_containers_to_remove.append(container)
                footnote_count += 1
            if footnotes:
                return footnotes
            for sidenote in element.select("span.sidenote"):
                sidenote.decompose()
            return footnotes

        footnote_count = 1
        for container in containers:
            content = container.select_one("span.footnote, span.sidenote, span.footnoteContent")
            if not content:
                continue
            content_clone = self._clone_tag(content)
            footnotes[footnote_count] = FootnoteData(
                content=content_clone,
                original_id=str(footnote_count),
                refs=[f"fnref:{footnote_count}"],
            )
            ref = self.create_footnote_reference(str(footnote_count), f"fnref:{footnote_count}")
            container.replace_with(ref)
            footnote_count += 1

        return footnotes

    def collect_aside_footnotes(self, element: Tag) -> dict[int, FootnoteData]:
        """Collect footnotes from aside > ol[start] patterns."""
        footnotes: dict[int, FootnoteData] = {}
        ols = element.select("aside > ol[start]")
        if not ols:
            return footnotes

        for ol in ols:
            aside = ol.parent
            if not isinstance(aside, Tag):
                continue
            footnote_number = int(ol.get("start", "0"))
            if footnote_number < 1:
                continue
            items = ol.select("li")
            if not items:
                continue

            content_div = self.doc.new_tag("div")
            if len(items) == 1:
                self._transfer_content(self._clone_tag(items[0]), content_div)
            else:
                for li in items:
                    p = self.doc.new_tag("p")
                    self._transfer_content(self._clone_tag(li), p)
                    content_div.append(p)

            footnotes[footnote_number] = FootnoteData(
                content=content_div, original_id=str(footnote_number), refs=[]
            )
            aside.decompose()

        return footnotes

    def standardize_footnotes(self, element: Tag) -> None:
        """Main entry point: standardize all footnotes in element."""
        # Handle CSS sidenotes first
        sidenotes = self.collect_inline_sidenotes(element)

        # Collect regular footnotes
        footnotes = self.collect_footnotes(element)

        # Merge aside footnotes
        aside_footnotes = self.collect_aside_footnotes(element)
        for num, data in aside_footnotes.items():
            if num not in footnotes:
                footnotes[num] = data

        # Standardize inline references
        inline_refs = element.select(FOOTNOTE_INLINE_REFERENCES)
        sup_groups: dict[Tag, list[Tag]] = {}

        for el in inline_refs:
            if not isinstance(el, Tag) or el.parent is None:
                continue

            footnote_id = ""

            # Various reference formats
            if el.has_attr("class") and "footnoteref" in el.get("class", []):
                link = el.select_one('a[id^="footnoteref-"]')
                if link:
                    match = re.match(r"^footnoteref-(\d+)$", link.get("id", ""))
                    if match:
                        footnote_id = match.group(1)
            elif el.name == "a" and el.get("id", "").startswith("ref-link"):
                footnote_id = el.get_text(strip=True)
            elif el.has_attr("role") and el.get("role") == "doc-biblioref":
                xml_rid = el.get("data-xml-rid", "")
                if xml_rid:
                    footnote_id = xml_rid
                else:
                    href = el.get("href", "")
                    if href.startswith("#core-R"):
                        footnote_id = href.replace("#core-", "")
            elif el.name == "a" and (
                "footnote-anchor" in el.get("class", [])
                or el.select_one("span.footnote-hovercard-target")
            ):
                fid = el.get("id", "").replace("footnote-anchor-", "")
                if fid:
                    footnote_id = fid.lower()
            elif el.name == "cite" and "ltx_cite" in el.get("class", []):
                links = el.select("a")
                if links:
                    refs_list: list[Tag] = []
                    for link in links:
                        href = link.get("href", "")
                        pop = href.split("/")[-1] if "/" in href else href
                        match = re.search(r"bib\.bib(\d+)", pop)
                        if not match:
                            continue
                        citation_id = match.group(1).lower()
                        entry_num = None
                        for fn_num, fn_data in footnotes.items():
                            if fn_data.original_id == citation_id:
                                entry_num = fn_num
                                break
                        if entry_num is None:
                            continue
                        fn_data = footnotes[entry_num]
                        ref_id = f"fnref:{entry_num}-{len(fn_data.refs) + 1}" if fn_data.refs else f"fnref:{entry_num}"
                        fn_data.refs.append(ref_id)
                        refs_list.append(self.create_footnote_reference(str(entry_num), ref_id))
                    if refs_list:
                        container = self._find_outer_footnote_container(el)
                        for i, ref in enumerate(refs_list):
                            if i > 0:
                                container.insert_before(NavigableString(" "))
                            container.insert_before(ref)
                        container.decompose()
                        continue
            elif el.name == "sup" and "reference" in el.get("class", []):
                for link in el.select("a"):
                    href = link.get("href", "")
                    if href:
                        pop = href.split("/")[-1]
                        match = re.search(r"(?:cite_note|cite_ref)-(.+)", pop)
                        if match:
                            footnote_id = match.group(1).lower()
            elif el.name == "sup" and el.get("id", "").startswith("fnref:"):
                footnote_id = el.get("id", "").replace("fnref:", "").lower()
            elif el.name == "sup" and el.get("id", "").startswith("fnr"):
                footnote_id = re.sub(r"^fnr", "", el.get("id", "")).lower()
            elif el.name == "span" and "footnote-reference" in el.get("class", []):
                footnote_id = el.get("data-footnote-id", "")
                if not footnote_id and el.get("id", "").startswith("fnref"):
                    footnote_id = re.sub(r"^fnref", "", el.get("id", "")).lower()
            elif el.name == "span" and "footnote-link" in el.get("class", []):
                footnote_id = el.get("data-footnote-id", "")
            elif el.name == "a" and "citation" in el.get("class", []):
                footnote_id = el.get_text(strip=True)
            elif el.name == "a" and el.get("id", "").startswith("fnref"):
                footnote_id = re.sub(r"^fnref", "", el.get("id", "")).lower()
            else:
                href = el.get("href", "")
                if href:
                    footnote_id = href.lstrip("#").lower()

            if footnote_id:
                footnote_entry = None
                for fn_num, fn_data in footnotes.items():
                    if fn_data.original_id == footnote_id.lower():
                        footnote_entry = (fn_num, fn_data)
                        break

                if footnote_entry:
                    fn_num, fn_data = footnote_entry
                    ref_id = f"fnref:{fn_num}-{len(fn_data.refs) + 1}" if fn_data.refs else f"fnref:{fn_num}"
                    fn_data.refs.append(ref_id)

                    container = self._find_outer_footnote_container(el)

                    if container.name == "sup":
                        sup_groups.setdefault(container, []).append(
                            self.create_footnote_reference(str(fn_num), ref_id)
                        )
                    else:
                        container.replace_with(
                            self.create_footnote_reference(str(fn_num), ref_id)
                        )

        # Fallback: match unmatched footnotes
        unmatched = {n: d for n, d in footnotes.items() if not d.refs}
        if unmatched:
            footnote_id_map = {d.original_id: (n, d) for n, d in unmatched.items()}
            footnote_num_map = {str(n): (n, d) for n, d in unmatched.items()}

            # Pass 1: Match by fragment link
            for link in element.select('a[href*="#"]'):
                if not isinstance(link, Tag) or link.parent is None:
                    continue
                if link.find_parent(attrs={"id": re.compile(r"^fnref:")}):
                    continue
                if link.find_parent(attrs={"id": "footnotes"}):
                    continue
                if self.generic_container and self.generic_container in link.parents:
                    continue
                if any(ge in link.parents for ge in self.generic_elements):
                    continue

                href = link.get("href", "")
                fragment = href.split("#")[-1].lower() if "#" in href else ""
                if not fragment:
                    continue

                entry = footnote_id_map.get(fragment)
                if not entry:
                    continue

                text = link.get_text(strip=True)
                if not re.match(r"^[\[\(]?\d{1,4}[\]\)]?$", text):
                    continue

                fn_num, fn_data = entry
                ref_id = f"fnref:{fn_num}-{len(fn_data.refs) + 1}" if fn_data.refs else f"fnref:{fn_num}"
                fn_data.refs.append(ref_id)

                container = self._find_outer_footnote_container(link)
                container.replace_with(
                    self.create_footnote_reference(str(fn_num), ref_id)
                )

            # Pass 2: Match sup/span with numeric text
            still_unmatched = {n: d for n, d in footnotes.items() if not d.refs}
            if still_unmatched:
                footnote_id_map2 = {d.original_id: (n, d) for n, d in still_unmatched.items()}
                footnote_num_map2 = {str(n): (n, d) for n, d in still_unmatched.items()}

                for el in element.select("sup, span.footnote-ref"):
                    if not isinstance(el, Tag) or el.parent is None:
                        continue
                    if el.get("id", "").startswith("fnref:"):
                        continue
                    if el.find_parent(attrs={"id": "footnotes"}):
                        continue
                    text = el.get_text(strip=True)
                    match = re.match(r"^[\[\(]?(\d{1,4})[\]\)]?$", text)
                    if not match:
                        continue
                    num_str = match.group(1)
                    entry = footnote_num_map2.get(num_str) or footnote_id_map2.get(num_str)
                    if not entry:
                        continue
                    fn_num, fn_data = entry
                    if fn_data.refs:
                        continue
                    ref_id = f"fnref:{fn_num}"
                    fn_data.refs.append(ref_id)

                    container = self._find_outer_footnote_container(el)
                    container.replace_with(
                        self.create_footnote_reference(str(fn_num), ref_id)
                    )

        # Handle grouped references
        for container, references in sup_groups.items():
            if references and container.parent:
                for i, ref in enumerate(references):
                    container.insert_before(ref)
                container.decompose()

        # Detect if the original HTML had a labeled footnote section (e.g. GitHub Flavored Markdown
        # uses <section data-footnotes> with an sr-only h2 heading "Footnotes"). That h2 gets
        # stripped by _remove_by_selector before we run, so we check for the section attribute.
        has_data_footnotes_section = bool(element.select("section[data-footnotes]"))

        # Create the standardized footnote list
        new_list = self.doc.new_tag("div")
        new_list["id"] = "footnotes"
        existing_heading = None
        for child in reversed(list(element.children)):
            if not isinstance(child, Tag):
                continue
            if child.name == "br":
                continue
            existing_heading = child
            break
        if (
            has_data_footnotes_section
            and not (
                isinstance(existing_heading, Tag)
                and existing_heading.name in ("h1", "h2", "h3", "h4", "h5", "h6")
                and existing_heading.get_text(" ", strip=True).lower() == "footnotes"
            )
        ):
            heading = self.doc.new_tag("h2")
            heading.string = "Footnotes"
            new_list.append(heading)
        ordered_list = self.doc.new_tag("ol")

        all_footnotes = {**sidenotes, **footnotes}
        for number in sorted(all_footnotes.keys()):
            data = all_footnotes[number]
            item = self.create_footnote_item(number, data.content, data.refs)
            ordered_list.append(item)

        # Remove original footnote lists
        for list_el in element.select(FOOTNOTE_LIST_SELECTORS):
            if list_el.parent:
                list_el.decompose()

        # Remove generically-detected containers
        if self.generic_container and self.generic_container.parent:
            self.generic_container.decompose()
        for el in self.generic_elements:
            if el.parent:
                el.decompose()
        for el in self.extra_containers_to_remove:
            if el.parent:
                el.decompose()

        # Strip trailing <hr>
        self._remove_orphaned_dividers(element)

        if ordered_list.contents:
            new_list.append(ordered_list)
            element.append(new_list)

    # --- Helper methods ---

    def _parse_footnote_num(self, el: Tag) -> Optional[int]:
        """Return footnote number if el is a <p> whose first child is <sup>N> or <strong>N."""
        first = el.find(True)
        if not first or first.name not in ("sup", "strong"):
            return None
        text = first.get_text(strip=True)
        try:
            num = int(text)
            return num if num >= 1 and str(num) == text else None
        except ValueError:
            return None

    def _cross_validate(self, element: Tag, paragraphs: list[tuple[int, Tag]]) -> bool:
        """Check if at least 2 paragraph numbers appear as bare <sup>N> inline refs."""
        numbered_nums = {p[0] for p in paragraphs}
        para_els = {id(p[1]) for p in paragraphs}
        matched: set[int] = set()
        for sup in element.select("sup"):
            if not isinstance(sup, Tag):
                continue
            # Check if sup is inside a footnote paragraph (using identity)
            parent = sup.parent
            is_in_footnote = False
            while parent:
                if id(parent) in para_els:
                    is_in_footnote = True
                    break
                parent = parent.parent
            if is_in_footnote:
                continue
            if sup.find("a"):
                continue
            text = sup.get_text(strip=True)
            try:
                n = int(text)
                if n >= 1 and str(n) == text and n in numbered_nums:
                    matched.add(n)
            except ValueError:
                pass
        return len(matched) >= 2

    def _find_loose_footnote_paragraphs(
        self, element: Tag
    ) -> Optional[tuple[list[tuple[int, Tag]], list[Tag]]]:
        """Find loose footnote paragraphs after <hr> or at the end."""
        all_ps = element.select("p")
        if not all_ps:
            return None
        container = all_ps[-1].parent if all_ps[-1].parent else element
        children = [c for c in container.children if isinstance(c, Tag)]
        if not children:
            return None

        # Method 1: <hr> section boundary
        for i in range(len(children) - 1, -1, -1):
            if children[i].name == "hr":
                paragraphs: list[tuple[int, Tag]] = []
                for j in range(i + 1, len(children)):
                    num = self._parse_footnote_num(children[j])
                    if num is not None:
                        paragraphs.append((num, children[j]))
                if len(paragraphs) >= 2 and self._cross_validate(element, paragraphs):
                    return paragraphs, children[i:]
                break

        # Method 2: backwards scan
        trailing: list[tuple[int, Tag]] = []
        first_idx = -1
        for i in range(len(children) - 1, -1, -1):
            child = children[i]
            if child.name == "p":
                num = self._parse_footnote_num(child)
                if num is not None:
                    trailing.insert(0, (num, child))
                    first_idx = i
                    continue
                break
            if child.name in ("ul", "ol", "blockquote"):
                continue
            break

        if len(trailing) >= 2 and self._cross_validate(element, trailing):
            to_remove = children[first_idx:]
            # Check for heading before first footnote
            prev = trailing[0][1].previous_sibling
            while prev and not isinstance(prev, Tag):
                prev = prev.previous_sibling
            if prev and prev.name and re.match(r"^h[1-6]$", prev.name):
                if _FOOTNOTE_SECTION_RE.match(prev.get_text(strip=True)):
                    to_remove.insert(0, prev)
            return trailing, to_remove

        return None

    def _find_outer_footnote_container(self, el: Tag) -> Tag:
        """Find the outermost container (span/sup) for a footnote ref."""
        current = el
        parent = el.parent
        while parent and isinstance(parent, Tag) and parent.name in ("span", "sup"):
            current = parent
            parent = parent.parent
        return current

    def _get_child_anchor_id(self, el: Tag) -> str:
        anchor = el.select_one("a[id], a[name]")
        if not anchor:
            return ""
        return (anchor.get("id", "") or anchor.get("name", "") or "").lower()

    def _find_matching_footnote_elements(
        self, container: Tag, fragment_set: set[str]
    ) -> list[tuple[Tag, str]]:
        results: list[tuple[Tag, str]] = []
        seen: set[str] = set()
        for el in container.select("li, p, div"):
            id_val = ""
            el_id = el.get("id", "").lower()
            if el_id and el_id in fragment_set:
                id_val = el_id
            elif not el_id:
                anchor_id = self._get_child_anchor_id(el)
                if anchor_id and anchor_id in fragment_set:
                    id_val = anchor_id
            if id_val and id_val not in seen:
                results.append((el, id_val))
                seen.add(id_val)
        return results

    def _remove_backrefs(self, el: Tag) -> None:
        """Remove back-reference links from footnote content."""
        for backref in list(el.select(".mw-cite-backlink")):
            backref.decompose()
        for a in list(el.select("a")):
            text = a.get_text(strip=True)
            text = re.sub(r"[\uFE0E\uFE0F]", "", text)
            if re.match(r"^[\u21a9\u21a5\u2191\u21b5\u2934\u2935\u23ce]+$", text):
                a.decompose()
            elif "footnote-backref" in a.get("class", []):
                a.decompose()
        # Clean up trailing whitespace/punctuation
        while el.children:
            last = list(el.children)[-1]
            if isinstance(last, NavigableString) and re.match(r"^[\s,.;]*$", str(last)):
                last.extract()
            else:
                break

    def _clone_tag(self, tag: Tag) -> Tag:
        """Deep clone a tag."""
        import copy
        return copy.copy(tag)  # BeautifulSoup's copy is deep for Tag

    def _transfer_content(self, source: Tag, target: Tag) -> None:
        """Move all children from source to target."""
        for child in list(source.children):
            child.extract()
            target.append(child)

    def _remove_orphaned_dividers(self, element: Tag) -> None:
        """Remove leading and trailing <hr> elements."""
        for _ in range(50):
            if not element.contents:
                break
            node = element.contents[0]
            if isinstance(node, NavigableString) and not str(node).strip():
                node.extract()
                continue
            if isinstance(node, Tag) and node.name == "hr":
                node.extract()
            else:
                break
        for _ in range(50):
            if not element.contents:
                break
            node = element.contents[-1]
            if isinstance(node, NavigableString) and not str(node).strip():
                node.extract()
                continue
            if isinstance(node, Tag) and node.name == "hr":
                node.extract()
            else:
                break
