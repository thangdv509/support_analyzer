# Product Metafields

## 🔎 What Are Shopify Product Metafields?

\
&#x20;  "***Shopify metafields let you store additional, specialized information about your products—beyond what's available in the standard admin fields. They’re useful for showing things like material composition, potency, size details, or ingredient breakdowns***."

⇒ DECO uses product metafields to generate dynamic labels and badges automatically<mark style="color:blue;">**—so all using the same design—just powered by different metafield values.**</mark>

## 🗂️ Common Use Cases

### 1. Show Values Of Product Meta Field Dynamically

#### 🌿 **Cannabis Products**

* Show **THCa flower potency** or **strain type** on product badges
* Display **CBD/THC ratios** dynamically

<figure><img src="/files/KO9c0JCbdkO5exrowVIW" alt=""><figcaption></figcaption></figure>

#### 🕯️ **Handmade Goods**

* Highlight **soy wax percentage** for candles

<figure><img src="/files/JLRocl9Saksl7DiROyA8" alt=""><figcaption></figcaption></figure>

### 2. Show Exact Values Of Product Meta Field&#x20;

#### &#x20;🎀 Skincare Products

* Display the exact skin type that the product suits
* Based on what's written in-app

<figure><img src="/files/cKAtcfIvD1hekcqnX13X" alt=""><figcaption></figcaption></figure>

<figure><img src="/files/LdxRi6FT5X4oZ2T2Ze5A" alt=""><figcaption></figcaption></figure>

## ✅ Preparations

Before starting, you need:

* [x] DECOPlan: Growth/Unlimited
* [x] Product metafields created in your Shopify admin
* [x] Metafield values assigned to your products

For example:&#x20;

<figure><img src="/files/5SRbwCh4pYwOLocWiBgq" alt=""><figcaption></figcaption></figure>

## ✨Step-by-step Setup

We'll walk through **two use cases**:

1. Show <mark style="color:blue;">**dynamic**</mark> metafield value if it exists
2. Show <mark style="color:blue;">**specific**</mark> metafield values only

## 🔁 Shared Steps for Both Use Cases

🔹 <mark style="color:blue;">**Step 1: Create or Select Badge**</mark>

* Open DECO app >> Navigate to: Labels & Badges then:

→ If you **don't have any badges** yet: Click *<mark style="color:blue;">**"Create badge"**</mark>* >> Choose to create a *<mark style="color:blue;">**new Text Badge**</mark>*

→ If you **already have** badge(s): Click the *<mark style="color:blue;">**pencil icon**</mark>* to edit an existing badge

<figure><img src="/files/Coy0L75yL7NiCdgNIXjQ" alt=""><figcaption></figcaption></figure>

{% hint style="info" %}
This badge will act **as a dynamic template using metafield data**
{% endhint %}

<mark style="color:blue;">🔹</mark> <mark style="color:blue;"></mark><mark style="color:blue;">**Step 2: Connect Metafield with AutoText**</mark>

* &#x20;Go to Badge **Content** → Click **AutoText**
* In the popping list, scroll down & choose: **Product Metafields**&#x20;

<div><figure><img src="/files/n6BQAJrXr76oPClkfn4D" alt=""><figcaption></figcaption></figure> <figure><img src="/files/I4OIHMGl1DRGAPJslvEg" alt=""><figcaption></figcaption></figure></div>

* Then a list of active meta fields will appear, *<mark style="color:blue;">**check the box**</mark>* to select >> *<mark style="color:blue;">**Click "Select"**</mark>* button to save the change.

<figure><img src="/files/B8de9hY9r7o4PXZA9fA9" alt=""><figcaption></figcaption></figure>

### 🎯 <mark style="color:blue;">Use Case 1: Show Values Of Product Meta Field Dynamically</mark>

#### 🔹 Step 3: Add Product Metafield

* Move to the "<mark style="color:blue;">**Products"**</mark> tab to select the metafield condition
* Scroll to the <mark style="color:blue;">**Metafield**</mark> >> Click <mark style="color:blue;">**+ Add Metafield**</mark>**&#x20;>>** ***Then, choose&#x20;**<mark style="color:blue;">**the same metafield name**</mark>**&#x20;as you selected in the last step*****&#x20;>>** Hit on <mark style="color:blue;">**"Select"**</mark> button

<div><figure><img src="/files/NLuO9LxgtAZKg2qCbrJy" alt=""><figcaption></figcaption></figure> <figure><img src="/files/2d9lrSQBi9eN7u27rMIw" alt=""><figcaption></figcaption></figure></div>

* After selecting your product metafield key >> <mark style="color:blue;">**Choose the option: "Exists"**</mark>&#x20;

<figure><img src="/files/TQDzlaHOIdsFSuskNmQO" alt=""><figcaption></figcaption></figure>

#### 🔹 Step 4: Preview & Verify&#x20;

* The app will <mark style="color:blue;">**automatically scan**</mark>**&#x20;your products&#x20;**<mark style="color:blue;">**and detect**</mark>**&#x20;which ones&#x20;**<mark style="color:blue;">**contain the keywords**</mark>**&#x20;related to the metafield key you selected.**\
  \
  👉 For those products, it will <mark style="color:blue;">**display the corresponding value**</mark>**&#x20;on the badge.**

**Example:**

* **Metafield Key:** care instruction
* **Condition:** *Exists*

<figure><img src="/files/GnrhL7GrLzOh9aOQqWAM" alt=""><figcaption></figcaption></figure>

→ In this case, <mark style="color:blue;">**any product**</mark>**&#x20;that&#x20;**<mark style="color:blue;">**includes data in the "care instruction"**</mark>**&#x20;metafield will&#x20;**<mark style="color:blue;">**automatically show a badge with that value.**</mark>\
\
\&#xNAN;*(See the image below for a visual example.)*

<figure><img src="/files/BMrfGsgfNQgpC2ALmjZ7" alt=""><figcaption></figcaption></figure>

### <mark style="color:blue;">🎲 Use Case 2: Show Exact Values Of Product Meta Field</mark>

#### 🔹 Step 3: Add Product Metafield&#x20;

* Move to the "<mark style="color:blue;">**Products"**</mark> tab to select the metafield condition
* Scroll to the <mark style="color:blue;">**Metafield**</mark> >> Click <mark style="color:blue;">**+ Add Metafield**</mark>**&#x20;>>** ***Then, choose&#x20;**<mark style="color:blue;">**the same metafield name**</mark>**&#x20;as you selected in the last step*****&#x20;>>** Hit on <mark style="color:blue;">**"Select"**</mark> button

<div><figure><img src="/files/NLuO9LxgtAZKg2qCbrJy" alt=""><figcaption></figcaption></figure> <figure><img src="/files/2d9lrSQBi9eN7u27rMIw" alt=""><figcaption></figcaption></figure></div>

* Choose the option: <mark style="color:blue;">**"Equal to"**</mark> >> Type in the <mark style="color:blue;">**Product metafield Value**</mark> in the white box

For example:

<figure><img src="/files/39kjACPkcM5QbLA3VMzK" alt=""><figcaption></figcaption></figure>

#### 🔹 Step 4: Preview & Verify

* The app will **automatically find products that have the** <mark style="color:blue;">**exact metafield value**</mark> you entered.&#x20;

&#x20;        👉 **Then&#x20;**<mark style="color:blue;">**show that value**</mark>**&#x20;on the badge for those products**<mark style="color:blue;">**.**</mark>

**Example:**

* **Metafield Key:** *care instruction*
* **Value:** *sunlight prefer*
* **Condition:** *Equal To*

<figure><img src="/files/QHVLSIVXNT7mghX4fHiO" alt=""><figcaption></figcaption></figure>

→ In this case, <mark style="color:blue;">**any product(s)**</mark>**&#x20;that include the metafield value&#x20;**<mark style="color:blue;">**"sunlight prefer"**</mark>**&#x20;will&#x20;**<mark style="color:blue;">**automatically**</mark>**&#x20;show a badge&#x20;**<mark style="color:blue;">**with that value.**</mark>\
\
🖼️ *(See image below for example)*

<figure><img src="/files/JCx2Eme1LMGCIuEYh0x1" alt=""><figcaption></figcaption></figure>

## ❗ Quick Troubleshooting

* **"No data"** → Double-check whether those <mark style="color:blue;">**products have the Product Metafield Value assigned yet OR**</mark> make sure the <mark style="color:blue;">**metafield key selected in AutoText matches**</mark> the one added in the <mark style="color:blue;">**Metafield section (under the Products tab).**</mark>
* **No display** → Notice <mark style="color:blue;">**Uppercase/ Lowercase letters**</mark> (e.g., `Linen` ≠ `linen`)

<figure><img src="/files/znzsksGPVorBChXdQDF8" alt=""><figcaption></figcaption></figure>

{% hint style="info" %}
For the option <mark style="color:blue;">**"Exists"**</mark> →  Only type the product metafield <mark style="color:blue;">**KEY**</mark>

While with the <mark style="color:blue;">**"Equal to**</mark>" →  Only type the product metafield <mark style="color:blue;">**VALUE**</mark>
{% endhint %}

## 📞 Need Help?

If you’re stuck or need our experts to check your settings:

👉 Contact directly with the live-chat **DECO Support** team  and include:

* Your <mark style="color:blue;">**badge name**</mark>
* <mark style="color:blue;">**Screenshots**</mark> of your <mark style="color:blue;">**Shopify metafield setup**</mark>
* <mark style="color:blue;">**An example link**</mark> should have the badge to display on your website


---

<!-- wiki-links:auto-generated, xem build_wiki_links.py -->
## Related pages
- Related: [Welcome](welcome.md), [DECO Product Badges](ourfeatures_decoproductbadges.md), [DECO Discounts](ourfeatures_decodiscounts.md), [DECO Product Badges](ourfeatures_decoproductbadges1.md), [DECO Product Banners](ourfeatures_decoproductbanners.md), [DECO Trust Badges](ourfeatures_decotrustbadges.md), [DECO Badge Group](ourfeatures_decobadgegroup.md), [DECO Analytics](ourfeatures_decoanalytics.md)
- Sub-pages: [List of Values Metafield](ourspecialfeatures_productmetafields_listofvaluesmetafield.md)
- Nav: « [DECO Analytics](ourfeatures_decoanalytics.md) | [Add Dynamic Content](ourspecialfeatures_adddynamiccontent.md) »
