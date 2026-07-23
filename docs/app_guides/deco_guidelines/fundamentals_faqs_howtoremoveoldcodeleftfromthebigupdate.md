# How to remove old code left from the big update?

{% hint style="info" %}
After upgrading the app using the Polaris 12 gallery of Shopify, all of DECO codes are moved into the DECO theme app extension, not existing in your theme.\
\
But, sometimes, there will be some files left in your theme. They do not impact your theme elements, or other factors such as loading speed, or SEO in any way. However, to remove them completely, please follow this instruction:
{% endhint %}

1. Go to **Themes** > **Edit codes**

<figure><img src="/files/WUgOIFEsEZkz0PRzT2lE" alt=""><figcaption></figcaption></figure>

2. Delete "**{% include 'scm-product-label-head' %}**" in file "**theme.liquid**"

* In the search bar, you search for "**theme.liquid**", then click to open the file. Next in the code, you search for "**scm**", then find the line "**{% include 'scm-product-label-head' %}**" to delete.

<figure><img src="/files/bsuKRh5KAC2G9ruX2n3e" alt=""><figcaption></figcaption></figure>

* If this file has "**\<!--Product-Label script. Don't modify or delete-- >**" below the code "**{% include 'scm-product-label-head' %}"**, you will also delete all that part or kindly contact us to delete those files for you more easily!

3. Remove all the file(s) that has **"scm"** in the title.

* In the search bar, you search for "**scm**", then find all the file with "**scm**" > click those files starting with "**scm**" > click this button ![](/files/U71a6H0LbBNUW3nxRLVK)

<figure><img src="/files/T2ETBojOB928692ibe50" alt=""><figcaption></figcaption></figure>

4. Remove all the file that has **"sma-deco-label.css"** in the title.

* In the search bar, you search for "**sma-deco-label.css**", then find the file to delete.

<figure><img src="/files/4EYhH9YFRsDOtGmCDXWx" alt=""><figcaption></figcaption></figure>


---

<!-- wiki-links:auto-generated, xem build_wiki_links.py -->
## Related pages
- Parent: [FAQs](fundamentals_faqs.md)
- Related: [How To Create An Effective Prompt For Our AI Image Generator?](fundamentals_faqs_howtocreateaneffectivepromptforouraiimagegenerator.md), [What Is The Recommendation For Self-Uploading Templates?](fundamentals_faqs_whatistherecommendationforselfuploadingtemplates.md), [How Do I Fix The Missing Label/Badge Issue On My Website ?](fundamentals_faqs_howdoifixthemissinglabelbadgeissueonmywebsite.md), [How To Position Labels Anywhere On Product Images ?](fundamentals_faqs_howtopositionlabelsanywhereonproductimages.md), [How To Make Label/Badge Have Same Size on Any Screen/Device ?](fundamentals_faqs_howtomakelabelbadgehavesamesizeonanyscreendevice.md), [How To Display DECO's Features on An Unpublished Theme?](fundamentals_faqs_howtodisplaydecosfeaturesonanunpublishedtheme.md), [Can I use the app for free?](fundamentals_faqs_caniusetheappforfree.md), [I own or manage multiple stores. Do I qualify for special pricing?](fundamentals_faqs_iownormanagemultiplestoresdoiqualifyforspecialpricing.md)
- Sub-pages: [What happen after you uninstall DECO ?](fundamentals_faqs_howtoremoveoldcodeleftfromthebigupdate_whathappenafteryouuninstalldeco.md)
- Nav: « [Mandatory rules for Text Label/ Text Badge/ Banner Content](fundamentals_faqs_mandatoryrulesfortextlabeltextbadgebannercontent.md) | [How To Display Labels On All Product Images?](fundamentals_faqs_howtodisplaylabelsonallproductimages.md) »
