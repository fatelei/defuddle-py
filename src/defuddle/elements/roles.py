"""Conversion of ARIA roles to semantic HTML elements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup, Tag


@dataclass
class RoleProcessingOptions:
    convert_paragraphs: bool = True
    convert_lists: bool = True
    convert_buttons: bool = True
    convert_links: bool = True


def default_role_processing_options() -> RoleProcessingOptions:
    return RoleProcessingOptions()


class RoleProcessor:
    """Handles conversion of ARIA roles to semantic HTML elements."""

    def __init__(self, doc: BeautifulSoup) -> None:
        self._doc = doc

    def process_roles(self, options: Optional[RoleProcessingOptions] = None) -> None:
        if options is None:
            options = default_role_processing_options()

        if options.convert_paragraphs:
            self._convert_paragraph_roles()

        if options.convert_lists:
            self._convert_list_roles()

        if options.convert_buttons:
            self._convert_button_roles()

        if options.convert_links:
            self._convert_link_roles()

    def _convert_paragraph_roles(self) -> None:
        for element in list(self._doc.select('[role="paragraph"]')):
            self._replace_element_tag(element, "p")

    def _convert_list_roles(self) -> None:
        for list_element in list(self._doc.select('[role="list"]')):
            is_ordered = self._is_ordered_list(list_element)

            new_tag_name = "ol" if is_ordered else "ul"

            for item_element in list(list_element.select('[role="listitem"]')):
                self._convert_list_item(item_element)

            self._replace_element_tag(list_element, new_tag_name)

    def _is_ordered_list(self, list_element: Tag) -> bool:
        for item_element in list_element.select('[role="listitem"]'):
            label_element = item_element.select_one(".label")
            if label_element:
                label_text = label_element.get_text(strip=True)
                if ")" in label_text or "." in label_text:
                    return True
        return False

    def _convert_list_item(self, item_element: Tag) -> None:
        for label in list(item_element.select(".label")):
            label.decompose()

        for para in list(item_element.select('[role="paragraph"]')):
            self._replace_element_tag(para, "p")

        self._replace_element_tag(item_element, "li")

    def _convert_button_roles(self) -> None:
        for element in list(self._doc.select('[role="button"]')):
            self._replace_element_tag(element, "button")

    def _convert_link_roles(self) -> None:
        for element in list(self._doc.select('[role="link"]')):
            self._replace_element_tag(element, "a")

    def _replace_element_tag(self, element: Tag, new_tag_name: str) -> None:
        attrs = {
            k: v for k, v in element.attrs.items() if k != "role"
        }

        inner_html = element.decode_contents()

        new_tag = self._doc.new_tag(new_tag_name, attrs=attrs)
        new_tag_contents = BeautifulSoup(inner_html, "html.parser")
        for child in list(new_tag_contents.children):
            new_tag.append(child.extract())

        element.replace_with(new_tag)
