import { Link, NavLink, Outlet, useLocation } from "react-router";
import { ErrorBoundary } from "./ErrorBoundary";
import { PitchMark } from "./Icons";
import { ThemeToggle } from "./ThemeToggle";

export function Layout() {
  const { pathname } = useLocation();
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="masthead">
        <div className="masthead__inner">
          <Link to="/" className="wordmark">
            <PitchMark className="wordmark__mark" />
            EPL Predictor
          </Link>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              Predict
            </NavLink>
            <NavLink to="/season">This season</NavLink>
            <NavLink to="/model">Model</NavLink>
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main id="main" className="page" tabIndex={-1}>
        {/* Keyed by path so a crash on one page clears when you navigate away. */}
        <ErrorBoundary key={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
      <footer className="footer">
        <div className="footer__inner">
          A statistical model, not betting advice. Unofficial: not affiliated with the Premier
          League or any club. Results data from football-data.co.uk.
        </div>
      </footer>
    </div>
  );
}
