# Search visibility and evidence review

## Public content sitemap

`site/sitemap.xml` lists canonical public website pages and the Bede tour.
The existing Cloudflare build copies it to the domain root. The legacy
`/trackers/` redirect and application/API/session routes are not content entries.
Do not add private learner URLs, temporary codes, query strings, or fragments.
The audience-discovery regression test compares the sitemap against the static
site's canonical pages and checks the separately built tour.

## Google Search Console: owner action required

An HTTP 200 response, permissive robots rules, or a live URL test does not
establish indexing. No connected Search Console account was available during
this update. There is no verified Google indexing result to report yet.

1. Open https://search.google.com/search-console/ and select the verified
   `agnusdei.ai` domain property or `https://agnusdei.ai/` URL-prefix property.
   If neither exists, complete Google's ownership-verification steps first.
2. In **Sitemaps**, submit `https://agnusdei.ai/sitemap.xml`. Record the last
   read date, processing status, and any errors.
3. Inspect each URL below in **URL Inspection**. Record the indexed-version
   status, Google-selected canonical, last crawl, and any exclusion reason.
4. Use **Test live URL** to diagnose current access problems. Keep its result
   distinct from the indexed-version result.
5. After the approved changes are live, request indexing of changed pages
   where appropriate. Requests are not guarantees or deadlines.
6. Share the Sitemaps/Page indexing exports and URL Inspection results for
   review. Do not share account passwords, cookies, or tokens.

Priority URLs:

- https://agnusdei.ai/
- https://agnusdei.ai/homeschool/
- https://agnusdei.ai/schools/
- https://agnusdei.ai/educators/
- https://agnusdei.ai/research/
- https://agnusdei.ai/bede/tour/
- https://agnusdei.ai/pilot/

Google guidance:

- https://support.google.com/webmasters/answer/9012289
- https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap
- https://developers.google.com/search/docs/appearance/ai-features

Googlebot governs Google Search crawling. Google-Extended is not a Google
Search ranking signal. Check both source robots.txt and Cloudflare's served
response before reporting crawler access.

## Keep audience descriptions concise

Use the existing homeschool, school, and co-op pages rather than adding
homepage sections. State the audience, purpose, K–8 learning levels and ages
5–15 plainly. Preserve separate family/co-op terms and the current
teacher-directed, synthetic-data-only school pilot scope. Age-specific search
examples do not narrow the product's full range.

## Evidence and educator experience

The audience pages link to the existing recorded Bede lessons and the
Research & Findings page. These are demonstrations and teaching-method
research, respectively; third-party studies are not Bede outcome trials.
The existing survey accepts firsthand experience, but permission to reply
by email is not permission to publish a testimonial.

No new Bede-specific educator testimonials or independently published
mentions were supplied for this update. Do not invent them.

As material becomes available:

1. Verify the original source and date. For an independent mention, confirm
   that it actually discusses Bede; identify sponsored or affiliated coverage.
2. For educator experience, confirm firsthand use and the educator's role.
   Obtain explicit permission for the exact public quote and attribution.
   Exclude student identifiers and private learning records.
3. Describe what the source observed. Separate a demonstration, reported
   experience, measured outcome, and independent review. Do not extrapolate
   other products' results or promise accelerated learning.
4. Add a short attributed extract or link to the relevant audience page or
   Research & Findings, with the original publication date and source link.
   Keep longer material off the homepage.
5. Review the wording, links, and any structured data for consistency. Obtain
   owner publication approval before pushing: a GitHub branch push can
   trigger the production Cloudflare build.

Indexing, rankings, and inclusion in Google or Gemini answers are separate
outcomes. None is established by schema, llms.txt, or crawler permissions alone.
