# Add Dynamic Content

## DETAILED DOCS

* First, on your app dashboard, click on "Label & Badge" > "Create Badge" > "Text badge"

<figure><img src="/files/l3Ssk0QXBhwvATWfeLe7" alt=""><figcaption></figcaption></figure>

* After that, click on "Auto Text" button, then choose 1 of your preferred&#x20;

<figure><img src="/files/mh4VY9X4RZsBj9t0gXR8" alt=""><figcaption></figcaption></figure>

<details>

<summary>To make setup easier and help you configure the correct conditions, we categorize AutoText into <strong>four main types.</strong> Please refer to the corresponding section for each type to understand how it works and when to use it.</summary>

</details>

{% hint style="info" %}
5 types of variables:&#x20;

* **Compare-at price**
* **DECO Discount**
* **Shopify Discount**
* **Others**
  {% endhint %}

#### 1. Compare-at Price&#x20;

<table><thead><tr><th width="161">Type</th><th width="406">Condition</th><th width="245">Example</th></tr></thead><tbody><tr><td>{SAVE_PERCENT}</td><td>Shows the percentage off of the product if the product has a Compare-at price set via Shopify Admin → Products → Price.</td><td>Save 20%</td></tr><tr><td>{SAVE_AMOUNT}</td><td>Shows the amount off of the product if the product has a Compare-at price set via Shopify Admin → Products → Price.</td><td>Save $30</td></tr></tbody></table>

#### 2. DECO discount

<table><thead><tr><th width="285">Type</th><th width="288">Condition</th><th width="245">Example</th></tr></thead><tbody><tr><td>{DISCOUNT_VALUE_PERCENT}</td><td>Shows the percentage off of the product if the product has an active discount set via DECO's discount program.</td><td>Save 20%</td></tr><tr><td>{DISCOUNT_VALUE_AMOUNT}</td><td>Shows the fixed amount off of the product if the product has an active discount set via DECO's discount program.</td><td>Example: Save $30</td></tr><tr><td>{DISCOUNT_CODE}</td><td>Shows the discount code of the product if the product has an active discount code set via DECO's discount program.</td><td>KOL_20%</td></tr><tr><td>{NEW_PRICE}</td><td>Shows the new price of the product if the product has an active discount set via DECO's discount program.</td><td>NOW $99</td></tr></tbody></table>

#### 3. Shopify Discount

<table><thead><tr><th width="285">Type</th><th width="288">Condition</th><th width="245">Example</th></tr></thead><tbody><tr><td>{DISCOUNT_VALUE_PERCENT}</td><td>Shows the percentage off of the product if the product has an active discount set via Shopify Admin → Discounts.</td><td>Save 20%</td></tr><tr><td>{DISCOUNT_VALUE_AMOUNT}</td><td>Shows the fixed amount off of the product if the product has an active discount set via Shopify Admin → Discounts.</td><td>Save $30</td></tr><tr><td>{DISCOUNT_CODE}</td><td>Shows the discount code of the product if the product has an active discount code set via Shopify Admin → Discounts.</td><td>KOL_20%</td></tr></tbody></table>

#### 4. Others

<table><thead><tr><th width="285">Type</th><th width="288">Condition</th><th width="245">Example</th></tr></thead><tbody><tr><td>{STOCK}</td><td>Shows the current stock quantity of the product.</td><td>ONLY 5 LEFT</td></tr><tr><td>{PRICE}</td><td>Shows the current selling price of the product.</td><td>Only $99</td></tr><tr><td>{DAYS_SINCE_RELEASE}</td><td>Shows the number of days since the product was published in your Shopify store.</td><td>NEW IN 3 DAYS</td></tr><tr><td>{PRODUCT_METAFIELD}</td><td>Shows a custom metafield value of the product if the product has a metafield set via Shopify Admin → Products → Metafields.</td><td>100% Cotton</td></tr><tr><td>{NUMBER_OF_REVIEW}</td><td>Shows the total number of reviews of the product from your review app (Judge.me, Loox, Trustoo, Junip, LAI Reviews, Air Reviews,...).</td><td>45 reviews</td></tr><tr><td>{AVERAGE_RATING}</td><td>Shows the average star rating of the product from your review app (Judge.me, Loox, Trustoo, Junip, LAI Reviews, Air Reviews,...).</td><td>5 stars</td></tr></tbody></table>

**NOTE:**&#x20;

1\. If you want your text will be in another lines: Insert \</br> into the text box&#x20;

2\. All content in the text box should be written in 1 line, please don't press "enter" on your keyboard

3\. This mark " is a special character, instead of using it, please use this mark '


---

<!-- wiki-links:auto-generated, xem build_wiki_links.py -->
## Related pages
- Related: [Welcome](welcome.md), [DECO Product Badges](ourfeatures_decoproductbadges.md), [DECO Discounts](ourfeatures_decodiscounts.md), [DECO Product Badges](ourfeatures_decoproductbadges1.md), [DECO Product Banners](ourfeatures_decoproductbanners.md), [DECO Trust Badges](ourfeatures_decotrustbadges.md), [DECO Badge Group](ourfeatures_decobadgegroup.md), [DECO Analytics](ourfeatures_decoanalytics.md)
- Nav: « [Product Metafields](ourspecialfeatures_productmetafields.md) | [Customer Conditions](ourspecialfeatures_customerconditions.md) »
