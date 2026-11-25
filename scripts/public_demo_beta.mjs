// Matches the API/browser endpoint: midnight after December 31 Central Time.
export const PUBLIC_DEMO_CLOSES_AT = '2027-01-01T06:00:00Z';
export const publicDemoClosed = (now = Date.now()) =>
  now >= Date.parse(PUBLIC_DEMO_CLOSES_AT);

export async function verifyClosedDemo(page, entryButtonLabel, timeout) {
  await page.getByRole('heading', { name: 'The demo beta has ended', exact: true })
    .waitFor({ state: 'visible', timeout });
  const onboarding = page.getByRole('link', { name: 'Request onboarding', exact: true });
  const email = page.getByRole('link', { name: 'info@agnusdei.ai', exact: true });
  if (!await onboarding.isVisible() || await onboarding.getAttribute('href') !== '/inquire/' ||
      !await email.isVisible() || await email.getAttribute('href') !== 'mailto:info@agnusdei.ai' ||
      await page.getByRole('button', { name: entryButtonLabel, exact: true }).count()) {
    throw new Error('Closed demo must retain onboarding contacts and remove demo entry.');
  }
}
