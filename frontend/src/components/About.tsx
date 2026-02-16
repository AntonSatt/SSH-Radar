import './About.css'

function About() {
  return (
    <div className="about">
      <h2 className="about-title">About SSH Radar</h2>

      <div className="about-content">
        <p>
          I'm a DevOps student in Stockholm, Sweden. When I started my program in September 2025,
          I was practicing on my Raspberry Pi at home and wanted to be able to access it when I was
          away. So I opened the SSH port (22) on my router.
        </p>

        <p>
          A day later, I started wondering if that was actually a smart thing to do. I ran{' '}
          <code>sudo lastb</code> on my Raspberry Pi and discovered a flood of IP addresses that
          had been trying to log in. They were bots &mdash; constantly scanning the internet for
          open SSH ports.
        </p>

        <p>
          Fast forward to January 2026, when we started learning about databases in the program. I
          needed to pick something to build a database around. A gym tracker? A movie catalog?
          Boring. Then I remembered <code>lastb</code>.
        </p>

        <p>
          I had just gotten two Oracle Free Tier servers and hadn't changed the default SSH port on
          them yet, so I already had almost a month of failed login data sitting there. Perfect.
        </p>

        <p>
          That's how SSH Radar was born &mdash; a real project built from a real "oops" moment,
          turning thousands of failed brute-force attempts into something visual and useful.
        </p>
      </div>

      <div className="about-author">
        <p>
          Built by{' '}
          <a href="https://antonsatt.com" target="_blank" rel="noopener noreferrer">
            Anton Sätterkvist
          </a>
        </p>
      </div>
    </div>
  )
}

export default About
