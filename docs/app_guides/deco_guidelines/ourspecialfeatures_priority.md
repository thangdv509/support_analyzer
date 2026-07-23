# Priority

## ✨ How "Priority" Can Help Control Badge Visibility?

### ✔️ Understanding Badge Priority & Visibility

* The Priority setting gives you precise *<mark style="color:$primary;">**control over which badges appear**</mark>* on a product *<mark style="color:$primary;">**when multiple display conditions are met**</mark>* simultaneously.&#x20;

⇒ This prevents your product images from becoming cluttered and *<mark style="color:$primary;">**ensures your most important marketing messages**</mark>* stand out!

### ✔️ The Priority Scale

The system uses a numerical ranking to determine importance:

* *<mark style="color:$primary;">**0**</mark>* is the *<mark style="color:$primary;">**Highest Priority**</mark>* (appears first/takes precedence).
* Larger numbers (*<mark style="color:$primary;">**1, 2, 3**</mark>*...) represent *<mark style="color:$primary;">**Lower Priority**</mark>*.

### ✔️ Key Feature: "Hide if product has higher priority badges"

* Each badge has a checkbox labeled "Hide if product has higher priority badges."&#x20;

⇒ This setting *<mark style="color:$primary;">**determines if a badge should disappear**</mark>* when it "competes" with a more important one.

## ✨ How Priority Logic Works

### 1. Badge With Different Priorities

⇒ If *<mark style="color:$primary;">**two badges have different priority numbers**</mark>*, the system looks at the *<mark style="color:$primary;">**"Hide..." checkbox**</mark>* of the lower-priority badge.

* <mark style="color:$primary;">**If both checked**</mark>: The lower-priority badge will be hidden.
* <mark style="color:$primary;">**If both unchecked**</mark>: Both badges will be displayed (unless the higher-priority badge also has a "Hide" rule).

> Example:
>
> * Badge A: "Free Shipping" | Priority: 0 | "Hide..." box: Unchecked.
> * Badge B: "Personalize It" | Priority: 1 | "Hide..." box: Checked.
> * Result: Only "Free Shipping" is displayed because Badge B is set to hide whenever a higher priority (0) is present.

<figure><img src="/files/Ai6BM9UcZUHfULrloeLs" alt=""><figcaption></figcaption></figure>

### 2. Badges with the Same Priority

| <mark style="color:$primary;">**Scenario**</mark> | <mark style="color:$primary;">**Behavior**</mark>      | <mark style="color:$primary;">**Result**</mark> |
| ------------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| Both have "Hide" checked                          | The older badge (created first) wins.                  | Only the first-created badge shows.             |
| Neither has "Hide" checked                        | No hiding rules are triggered.                         | Both badges are displayed.                      |
| Only one has "Hide" checked                       | The "Hide" rule only triggers for *higher* priorities. | Both badges are displayed.                      |

Example: *<mark style="color:$primary;">**Both have "Hide..." checked**</mark>*

* Badge A: "New Arrival" (Created June 17). Priority: 0. "Hide" Checked.
* Badge B: "Pre-order" (Created June 20). Priority: 0. "Hide" Checked.

⇒ **Result:** "New Arrival" is displayed because it was created first.

Example: *<mark style="color:$primary;">**Neither has "Hide..." checked**</mark>*

**⇒ Result:** Both badges display

<figure><img src="/files/fadRLCzEtMEbfSMdK4B2" alt=""><figcaption></figcaption></figure>

Exampl&#x65;**:&#x20;***<mark style="color:$primary;">**Only one has "Hide..." checked**</mark>*

**⇒** **Result:** Both badges display

* The "Hide..." setting only works when comparing badges with *different* priorities

<figure><img src="/files/xfz3XhokwOiCWfWVO5Hc" alt=""><figcaption></figcaption></figure>

#### 3. Summary Table&#x20;

| **Priority Level** | **Hide Box Status** | **Outcome**                              |
| ------------------ | ------------------- | ---------------------------------------- |
| Highest (0)        | N/A                 | Always displays.                         |
| Lower (1+)         | Checked             | Hidden if a Priority 0 badge exists.     |
| Lower (1+)         | Unchecked           | Displays alongside the Priority 0 badge. |


---

<!-- wiki-links:auto-generated, xem build_wiki_links.py -->
## Related pages
- Related: [Welcome](welcome.md), [DECO Product Badges](ourfeatures_decoproductbadges.md), [DECO Discounts](ourfeatures_decodiscounts.md), [DECO Product Badges](ourfeatures_decoproductbadges1.md), [DECO Product Banners](ourfeatures_decoproductbanners.md), [DECO Trust Badges](ourfeatures_decotrustbadges.md), [DECO Badge Group](ourfeatures_decobadgegroup.md), [DECO Analytics](ourfeatures_decoanalytics.md)
- Nav: « [Add Translations For Content](ourspecialfeatures_addtranslationsforcontent.md) | [Show Badge Based On Store Languages](ourspecialfeatures_showbadgebasedonstorelanguages.md) »
